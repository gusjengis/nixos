"""Offline tests: context nesting, question caching and generated views."""
import importlib.util
import array
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import yaml

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('note_score', HERE / 'note-score.py')
ns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ns)
ex = ns.load_extract(HERE / 'note-extract.py')


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name)
        (self.vault / 'Contexts').mkdir()
        for name, parent in [('Health', None), ('Sleep', 'Health'), ('Bedtime', 'Sleep')]:
            meta = {'description': name}
            if parent:
                meta['parent'] = f'[[Contexts/{parent}]]'
            (self.vault / 'Contexts' / f'{name}.md').write_text(ex.join_note(meta, 'My text\n'))
        self.ctx = ns.Contexts(ex, self.vault)

    def test_specific_membership_and_rollup(self):
        answers = {ns.context_qid(n): {'noul': 0.9} for n in self.ctx.notes}
        self.assertEqual(ns.assign(self.ctx, answers), ['Bedtime'])
        self.assertEqual(self.ctx.subtree('Health'), ['Health', 'Sleep', 'Bedtime'])
        views = ns.context_views(self.ctx, 'Health')
        base = yaml.safe_load(views.split('```base\n')[1].split('```')[0])
        self.assertEqual(base['views'][0]['name'], 'Next up')
        self.assertIn('Contexts/Bedtime', base['filters']['and'][0])
        body = ns.with_views('My text\n', views)
        self.assertTrue(body.startswith('My text\n'))
        self.assertEqual(ns.with_views(body, views), body)

    def test_cycle_does_not_loop(self):
        path = self.vault / 'Contexts/Health.md'
        path.write_text(ex.join_note({'description': 'Health', 'parent': '[[Contexts/Bedtime]]'}, ''))
        ctx = ns.Contexts(ex, self.vault)
        for name in ctx.notes:
            self.assertLess(len(ctx.ancestors(name)), 3)

    def test_dealt_with_excluded_from_scoring_but_kept_in_history(self):
        for kind in ns.SCORED_TYPES:
            self.assertTrue(ns.eligible(ex, {'types': [kind], 'status': 'todo'}))
            for status in ('done', 'dropped', 'dealt-with'):
                self.assertFalse(ns.eligible(ex, {'types': [kind], 'status': status}))
            # Preserve shipped someday scoring behavior; open views hide it.
            self.assertTrue(ns.eligible(ex, {'types': [kind], 'status': 'someday'}))
        base = yaml.safe_load(ns.context_views(self.ctx, 'Health').split('```base\n')[1].split('```')[0])
        for view in base['views']:
            if view['name'] == 'Everything':
                self.assertNotIn('filters', view)
            else:
                self.assertIn('status != "dealt-with"', view['filters']['and'])
        thoughts = yaml.safe_load((HERE / 'Thoughts.base').read_text())
        for view in thoughts['views']:
            if view['name'] != 'Recent':
                self.assertIn('status != "dealt-with"', view['filters']['and'])
            else:
                self.assertNotIn('filters', view)
        for block in ns.DASHBOARD.split('```base\n')[2:]:
            base = yaml.safe_load(block.split('```')[0])
            self.assertIn('status != "dealt-with"', base['filters']['and'])

    def test_closed_context_members_count_as_history_not_open(self):
        (self.vault / 'Thoughts').mkdir()
        for name, status in [('Open', 'todo'), ('Closed', 'dealt-with')]:
            (self.vault / f'Thoughts/{name}.md').write_text(ex.join_note({
                'types': ['idea'], 'status': status, 'score': 0.9,
            }, 'Test'))
        summary = ns.context_summaries(ex, self.ctx, ex.Store(self.vault), {
            'Thoughts/Open': ['Health'], 'Thoughts/Closed': ['Health'],
        })['Health']
        self.assertEqual(summary['open'], 1)
        self.assertEqual(summary['total'], 2)
        self.assertEqual(summary['top'], ['[[Thoughts/Open]]'])

    def test_dealt_with_target_does_not_boost_blocker_score(self):
        (self.vault / 'Thoughts').mkdir()
        for name, meta in [('Blocker', {'types': ['task'], 'blocks': ['[[Thoughts/Target]]']}),
                           ('Target', {'types': ['idea'], 'status': 'dealt-with'})]:
            (self.vault / f'Thoughts/{name}.md').write_text(ex.join_note(meta, 'Test'))
        store = ex.Store(self.vault)
        facets = [{'name': 'Health', 'id': 'health', 'weight': 1, 'aim': 'Be healthy'}]
        questions = ns.score_questions(facets, ns.build_state(ex, store, 'Thoughts/Blocker'))
        answers = {qid: {'score': 0} for qid in questions}
        result = ns.combine(ex, store, 'Thoughts/Blocker', questions, answers, facets, ns.DEFAULT_MIX)
        self.assertNotIn(' · blocks ', result['score-parts'])
        self.assertEqual(result['score'], ns.DEFAULT_MIX['quick'])

    def test_refresh_views_offline_preserves_assignments_and_user_content(self):
        (self.vault / 'Thoughts').mkdir()
        originals = {}
        for name, status, score in [('Open', 'todo', 0.3), ('Later', 'someday', 0.6),
                                    ('Closed', 'dealt-with', 0.99), ('Done', 'done', 0.9),
                                    ('Dropped', 'dropped', 0.8)]:
            path = self.vault / f'Thoughts/{name}.md'
            path.write_text(ex.join_note({
                'types': ['idea'], 'status': status, 'status-source': 'manual',
                'contexts': ['[[Contexts/Sleep]]'], 'custom': 'keep',
                'score': score, 'score-facet': 'Health', 'score-parts': 'old', 'score-unsure': True,
            }, 'User thought\n\n> Source quote\n'))
            originals[name] = path.read_bytes()
        context = self.vault / 'Contexts/Sleep.md'
        prefix, suffix = 'User context text\n\n', '\n\nUser footer\n'
        context.write_text(ex.join_note({
            'description': 'Sleep', 'parent': '[[Contexts/Health]]', 'custom': ['keep'],
            'context-score': 100, 'open': 100, 'total': 100, 'top': ['old'],
        }, prefix + ns.GEN_BEGIN + '\nOld views\n' + ns.GEN_END + suffix))
        for name in ('Dashboard.md', 'Thoughts.base'):
            (self.vault / name).write_text('User-owned file, do not migrate here\n')

        argv = ['note-score', '--vault', str(self.vault), '--refresh-views']
        with patch.object(sys, 'argv', argv), \
                patch.object(ns, 'Asker', side_effect=AssertionError('no model calls')), \
                patch.object(ns, 'discover', side_effect=AssertionError('no discovery')), \
                patch.object(ns, 'parse_facets', side_effect=AssertionError('no facets required')), \
                patch.object(ns, 'open_cache', side_effect=AssertionError('no cache required')), \
                patch.object(ns.fcntl, 'flock', wraps=ns.fcntl.flock) as flock:
            ns.main()
            flock.assert_called_once()
            self.assertEqual(flock.call_args.args[1], ns.fcntl.LOCK_EX)
        self.assertTrue((self.vault / '.note-extract.lock').exists())
        self.assertFalse((self.vault / 'score.sqlite').exists())
        for name in ('Open', 'Later'):
            self.assertEqual((self.vault / f'Thoughts/{name}.md').read_bytes(), originals[name])
        for name in ('Closed', 'Done', 'Dropped'):
            meta, body = ex.split_note((self.vault / f'Thoughts/{name}.md').read_text())
            self.assertFalse(any(k in meta for k in ns.SCORE_FIELDS))
            self.assertEqual(meta['contexts'], ['[[Contexts/Sleep]]'])
            self.assertEqual(meta['custom'], 'keep')
            self.assertEqual(meta['status-source'], 'manual')
            self.assertEqual(body, 'User thought\n\n> Source quote\n')
        meta, body = ex.split_note(context.read_text())
        self.assertEqual(meta['custom'], ['keep'])
        self.assertEqual(meta['parent'], '[[Contexts/Health]]')
        self.assertEqual(meta['description'], 'Sleep')
        self.assertEqual(meta['open'], 2)
        self.assertEqual(meta['total'], 5)
        self.assertEqual(meta['top'], ['[[Thoughts/Later]]', '[[Thoughts/Open]]'])
        self.assertEqual(meta['context-score'], 0.3)
        self.assertTrue(body.startswith(prefix))
        self.assertTrue(body.endswith(suffix))
        self.assertNotIn('Old views', body)
        self.assertIn('status != "dealt-with"', body)
        health, _ = ex.split_note((self.vault / 'Contexts/Health.md').read_text())
        self.assertEqual(health['total'], 5)
        for name in ('Dashboard.md', 'Thoughts.base'):
            self.assertEqual((self.vault / name).read_text(), 'User-owned file, do not migrate here\n')
        refreshed = context.read_bytes()
        with patch.object(sys, 'argv', argv):
            ns.main()
        self.assertEqual(context.read_bytes(), refreshed)

    def test_refresh_views_respects_explicit_lock(self):
        shared = self.vault / 'shared-lock'
        with patch.object(sys, 'argv', ['note-score', '--vault', str(self.vault),
                                      '--refresh-views', '--lock', str(shared)]):
            ns.main()
        self.assertTrue(shared.exists())
        self.assertFalse((self.vault / '.note-extract.lock').exists())

    def test_cache_is_per_question(self):
        db = ns.open_cache(self.vault / 'cache')
        self.addCleanup(db.close)
        key = self.vault / 'key'
        key.write_text('fake')
        asker = ns.Asker(db, 'test', key, 1)
        q = {'a': {'type': 'noul', 'instructions': 'A'},
             'b': {'type': 'noul', 'instructions': 'B'}}
        payloads = []

        def fake(payload, _key):
            payloads.append(payload)
            return {'answers': {n: {'noul': 0.8} for n in payload['questions']}}

        with patch.object(ns, 'call_jev', fake):
            requests = {'Thoughts/Test': ({'thought': 'test'}, q)}
            asker.ask(requests)
            asker.ask(requests)
            self.assertEqual(len(payloads), 1)
            q['b'] = {'type': 'noul', 'instructions': 'B edited'}
            asker.ask(requests)
            self.assertEqual(list(payloads[1]['questions']), ['b'])

    def test_discovery_creates_only_once(self):
        (self.vault / 'Thoughts').mkdir()
        state = self.vault / 'extract'
        state.mkdir()
        with sqlite3.connect(state / 'extract.sqlite') as vectors:
            vectors.execute('create table vectors (path text, model text, chunk int, vec blob)')
            for i in range(5):
                rel = f'Thoughts/Woodworking {i}'
                (self.vault / f'{rel}.md').write_text(ex.join_note({'types': ['idea']}, 'Build a chair'))
                vectors.execute('insert into vectors values (?, ?, 0, ?)',
                                (rel, 'jina-v5-matching@2', array.array('f', [1, 0]).tobytes()))
        args = SimpleNamespace(lock=state / 'lock', vault=self.vault,
                               ollama_url='fake', discovery_model='fake')
        db = ns.open_cache(self.vault / 'cache')
        self.addCleanup(db.close)
        response = {'message': {'content': json.dumps({
            'coherent': True, 'name': 'Woodworking', 'description': 'Building furniture', 'parent': '',
        })}}
        store = ex.Store(self.vault)
        with patch.object(ex, 'post', return_value=response) as model:
            ns.discover(ex, store, self.ctx, args, db)
            ns.discover(ex, store, self.ctx, args, db)
            self.assertEqual(model.call_count, 1)
        meta, _ = ex.split_note((self.vault / 'Contexts/Woodworking.md').read_text())
        self.assertEqual(meta['origin'], 'discovered')


if __name__ == '__main__':
    unittest.main()

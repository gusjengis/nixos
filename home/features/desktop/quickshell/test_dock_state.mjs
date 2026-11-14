import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';

const source = readFileSync(new URL('./config/DockState.js', import.meta.url), 'utf8');
const state = runInNewContext(`${source}\n({ ancestry, normalize, resolve })`);
const plain = value => JSON.parse(JSON.stringify(value));
const finder = 'finder';

test('logical ancestry follows reparenting, not filesystem paths', () => {
    const nodes = [
        { id: 'a', path: '/a' },
        { id: 'b', path: '/b' },
        { id: 'child', parent_id: 'b', path: '/a/child' },
    ];
    assert.deepEqual(plain(state.ancestry(nodes, '/a/child')), ['/b', '/a/child']);
    assert.deepEqual(plain(state.ancestry(nodes, '/new')), ['/new']);
    assert.deepEqual(plain(state.ancestry(nodes, '')), []);
    nodes[1].parent_id = 'child';
    assert.deepEqual(plain(state.ancestry(nodes, '/a/child')), ['/b', '/a/child']);
});

test('legacy pins migrate in memory, preserving local order without mutating input', () => {
    const old = { version: 1, pinned: ['kitty', 'finder', 'kitty', 12], order: ['entry:kitty'] };
    assert.deepEqual(plain(state.normalize(old, finder)), {
        version: 2, pinned: ['kitty'], removed: [], order: ['entry:kitty'],
    });
    assert.equal(old.version, 1);
    assert.equal(old.pinned.length, 4);
});

test('nearest explicit pin/unpin wins, siblings remain isolated', () => {
    const states = {
        parent: { pinned: ['kitty', 'steam'] },
        child: { pinned: ['chromium'], removed: ['kitty'] },
        leaf: { pinned: ['kitty'], removed: ['steam'] },
        sibling: { pinned: ['other'] },
    };
    assert.deepEqual(plain(state.resolve(['parent', 'child'], states, finder)).pinned, ['steam', 'chromium']);
    assert.deepEqual(plain(state.resolve(['parent', 'child', 'leaf'], states, finder)).pinned, ['chromium', 'kitty']);
    assert.deepEqual(plain(state.resolve(['parent', 'sibling'], states, finder)).pinned, ['kitty', 'steam', 'other']);
});

test('order inherits until locally overridden; reorder does not freeze membership', () => {
    const states = {
        parent: { pinned: ['kitty', 'steam'], order: ['entry:steam', 'entry:kitty'] },
        child: { order: ['entry:kitty', 'entry:steam'] },
        next: { pinned: ['chromium'] },
    };
    assert.deepEqual(plain(state.resolve(['parent'], states, finder)).pinned, ['steam', 'kitty']);
    assert.deepEqual(plain(state.resolve(['parent', 'child'], states, finder)).pinned, ['kitty', 'steam']);
    assert.deepEqual(plain(state.resolve(['next', 'child'], states, finder)).pinned, ['chromium']);
});

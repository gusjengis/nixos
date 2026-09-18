import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import usage


class UsageNormalizationTests(unittest.TestCase):
    def test_claude_windows(self):
        result = usage.normalize_claude({
            "five_hour": {"utilization": 12.4, "resets_at": None},
            "seven_day": {"utilization": 67.8, "resets_at": "2026-09-12T01:00:00Z"},
        })

        self.assertEqual(result["windows"][0], {"label": "5h", "used": 12, "reset": None})
        self.assertEqual(result["windows"][1]["used"], 68)

    def test_openai_windows(self):
        result = usage.normalize_openai({
            "rate_limit": {
                "primary_window": {"used_percent": 3, "reset_at": 1789206412},
                "secondary_window": {"used_percent": 34, "reset_at": 1789483561},
            }
        }, "personal", True)

        self.assertEqual([item["used"] for item in result["windows"]], [3, 34])
        self.assertEqual(result["windows"][0]["reset"], 1789206412)
        self.assertEqual(result["id"], "openai-personal")
        self.assertTrue(result["active"])

    def test_missing_openai_limits_do_not_invent_headroom(self):
        self.assertEqual(usage.normalize_openai({}, "personal")["windows"], [])


class UnavailableTests(unittest.TestCase):
    def rate_limited(self):
        return urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)

    def test_keeps_cached_windows_and_marks_them_stale(self):
        cached = {"Anthropic": {"windows": [{"label": "5h", "used": 27, "reset": None}], "fetched_at": 10}}

        result = usage.unavailable("Anthropic", self.rate_limited(), cached)

        self.assertEqual(result["windows"][0]["used"], 27)
        self.assertEqual(result["error"], "rate limited")
        self.assertEqual(result["fetched_at"], 10)
        self.assertTrue(result["stale"])
        self.assertTrue(result["available"])

    def test_reports_no_windows_without_cache(self):
        result = usage.unavailable("Anthropic", self.rate_limited(), {})

        self.assertEqual(result["windows"], [])
        self.assertFalse(result["available"])


class CacheTests(unittest.TestCase):
    def test_round_trip_skips_stale_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quickshell" / "ai-usage.json"
            good = {"name": "OpenAI", "windows": [{"label": "5h", "used": 4, "reset": 1}], "fetched_at": 5}

            usage.write_cache(path, [good, {"name": "Anthropic", "stale": True, "windows": []}])

            self.assertEqual([entry["name"] for entry in json.loads(path.read_text())["providers"]], ["OpenAI"])
            self.assertEqual(usage.read_cache(path)["OpenAI"]["windows"][0]["used"], 4)

    def test_failing_provider_keeps_its_previous_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai-usage.json"
            cached = {"Anthropic": {"name": "Anthropic", "windows": [{"label": "5h", "used": 27, "reset": None}]}}
            good = {"name": "OpenAI", "windows": [{"label": "5h", "used": 4, "reset": 1}], "fetched_at": 5}

            usage.write_cache(path, [good, {"name": "Anthropic", "stale": True, "windows": []}], cached)

            stored = usage.read_cache(path)
            self.assertEqual(stored["Anthropic"]["windows"][0]["used"], 27)
            self.assertEqual(stored["OpenAI"]["windows"][0]["used"], 4)

    def test_missing_cache_is_empty(self):
        self.assertEqual(usage.read_cache(Path("/nonexistent/ai-usage.json")), {})


class AccountProfileTests(unittest.TestCase):
    def auth(self, account, access="access"):
        return {
            "type": "oauth",
            "access": access,
            "refresh": f"refresh-{account}",
            "expires": 4102444800000,
            "accountId": account,
        }

    def environment(self, directory):
        return mock.patch.dict("os.environ", {"XDG_DATA_HOME": directory})

    def test_save_rejects_account_already_in_other_profile(self):
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            home = Path(directory) / "home"
            usage.write_private_json(usage.auth_path(home), {"openai": self.auth("same")})
            usage.save_profile(home, "personal")

            with self.assertRaisesRegex(usage.AccountError, "already saved as Personal"):
                usage.save_profile(home, "business")

            self.assertFalse(usage.profile_path(home, "business").exists())

    def test_save_can_replace_its_own_slot_to_recover_a_dead_login(self):
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            home = Path(directory) / "home"
            usage.write_private_json(usage.auth_path(home), {"openai": self.auth("personal")})
            usage.save_profile(home, "personal")
            usage.write_private_json(usage.auth_path(home), {"openai": self.auth("reissued")})

            usage.save_profile(home, "personal")

            self.assertEqual(usage.read_profile(home, "personal")["accountId"], "reissued")

    def test_activate_preserves_other_providers_and_latest_active_token(self):
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            home = Path(directory) / "home"
            usage.store_profile(home, "personal", self.auth("personal", "old"))
            usage.store_profile(home, "business", self.auth("business"))
            usage.write_private_json(usage.auth_path(home), {
                "anthropic": {"type": "api", "key": "untouched"},
                "openai": self.auth("personal", "new"),
            })

            usage.activate_profile(home, "business")

            active = usage.read_json(usage.auth_path(home))
            self.assertEqual(active["openai"]["accountId"], "business")
            self.assertEqual(active["anthropic"]["key"], "untouched")
            self.assertEqual(usage.read_profile(home, "personal")["access"], "new")

    def test_status_reports_identity_without_tokens_or_refresh(self):
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            home = Path(directory) / "home"
            usage.store_profile(home, "personal", self.auth("personal"))
            usage.store_profile(home, "business", self.auth("business"))
            usage.write_private_json(usage.auth_path(home), {"openai": self.auth("business")})
            with mock.patch.object(usage, "refresh_openai_auth", side_effect=AssertionError("must not refresh")):
                self.assertEqual(usage.account_status(home), {
                    "ok": True, "active": "business", "saved": ["personal", "business"],
                })

    def test_conditional_switch_does_not_undo_another_switch(self):
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            home = Path(directory) / "home"
            usage.store_profile(home, "personal", self.auth("personal"))
            usage.store_profile(home, "business", self.auth("business"))
            usage.write_private_json(usage.auth_path(home), {"openai": self.auth("business")})
            with mock.patch.object(Path, "home", return_value=home), mock.patch.object(usage, "activate_profile") as activate:
                result = usage.account_command(["select", "business", "personal"])
                self.assertFalse(result["switched"])
                self.assertEqual(result["active"], "business")
                activate.assert_not_called()

    def test_conditional_switch_returns_new_active_identity(self):
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            home = Path(directory) / "home"
            usage.store_profile(home, "personal", self.auth("personal"))
            usage.store_profile(home, "business", self.auth("business"))
            usage.write_private_json(usage.auth_path(home), {"openai": self.auth("personal")})
            with mock.patch.object(Path, "home", return_value=home):
                result = usage.account_command(["select", "business", "personal"])
                self.assertTrue(result["switched"])
                self.assertEqual(result["active"], "business")

    def test_profile_files_are_private(self):
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            home = Path(directory) / "home"
            usage.store_profile(home, "personal", self.auth("personal"))
            path = usage.profile_path(home, "personal")

            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_missing_profile_becomes_save_card(self):
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            home = Path(directory) / "home"
            result = usage.fetch_openai_profile(home, "personal", False, {})

            self.assertFalse(result["saved"])
            self.assertEqual(result["error"], "not saved")
            self.assertEqual(result["profile"], "personal")

    def expired(self, account):
        return {**self.auth(account), "expires": 0}

    def test_dead_refresh_token_turns_the_card_back_into_a_save_button(self):
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            home = Path(directory) / "home"
            usage.store_profile(home, "personal", self.expired("personal"))
            rejected = urllib.error.HTTPError("url", 400, "Bad Request", {}, None)

            with mock.patch.object(usage, "request_json", side_effect=rejected):
                result = usage.fetch_openai_profile(home, "personal", False, {})

            self.assertFalse(result["saved"])
            self.assertEqual(result["error"], "saved login expired")

    def test_rejected_usage_token_turns_the_card_back_into_a_save_button(self):
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            home = Path(directory) / "home"
            usage.store_profile(home, "personal", self.auth("personal"))
            rejected = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)

            with mock.patch.object(usage, "request_json", side_effect=rejected):
                result = usage.fetch_openai_profile(home, "personal", False, {})

            self.assertFalse(result["saved"])
            self.assertEqual(result["error"], "saved login rejected")

    def test_rate_limit_keeps_the_profile_saved_and_shows_cached_numbers(self):
        with tempfile.TemporaryDirectory() as directory, self.environment(directory):
            home = Path(directory) / "home"
            usage.store_profile(home, "personal", self.auth("personal"))
            cached = {"openai-personal": {"windows": [{"label": "5h", "used": 42, "reset": None}], "fetched_at": 7}}
            throttled = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)

            with mock.patch.object(usage, "request_json", side_effect=throttled):
                result = usage.fetch_openai_profile(home, "personal", False, cached)

            self.assertTrue(result["saved"])
            self.assertEqual(result["error"], "rate limited")
            self.assertEqual(result["windows"][0]["used"], 42)


if __name__ == "__main__":
    unittest.main()

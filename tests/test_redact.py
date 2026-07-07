"""Redaction tests: every supported secret shape must be masked."""
from __future__ import annotations

import unittest

from hermes_os.redact import contains_secret, redact_obj, redact_text

FAKE_SK = "sk-or-v1-" + "f4ke" * 8
FAKE_TG = "8123456789:" + "AAf4keF4kef4keF4kef4keF4kef4keF4kef"[:35]
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJmYWtlIjoidHJ1ZSJ9.f4kef4kef4ke"
FAKE_APIFY = "apify_api_" + "f4ke" * 6
FAKE_SUPABASE = "sbp_" + "f4ke" * 6
FAKE_OPAQUE = "a1" * 25  # 50 chars, letters+digits


class TestRedactText(unittest.TestCase):
    def test_api_key(self):
        out = redact_text(f"using key {FAKE_SK} for calls")
        self.assertNotIn(FAKE_SK, out)
        self.assertIn("[REDACTED:api-key]", out)

    def test_telegram_token(self):
        out = redact_text(f"bot token {FAKE_TG} loaded")
        self.assertNotIn(FAKE_TG, out)
        self.assertIn("[REDACTED:telegram-token]", out)

    def test_jwt(self):
        out = redact_text(f"supabase anon: {FAKE_JWT}")
        self.assertNotIn(FAKE_JWT, out)
        self.assertIn("[REDACTED:jwt]", out)

    def test_bearer(self):
        # non key:value context → the bearer pattern itself fires
        out = redact_text("curl sent header with Bearer f4kef4kef4kef4kef4kef4ke today")
        self.assertNotIn("f4kef4kef4kef4kef4kef4ke", out)
        self.assertIn("[REDACTED:bearer]", out)

    def test_authorization_header_line_masked(self):
        # a line shaped `Authorization: ...` is caught by the env rule
        # (key name contains "auth") — more aggressive, equally safe
        out = redact_text("Authorization: Bearer f4kef4kef4kef4kef4kef4ke")
        self.assertNotIn("f4kef4kef4kef4kef4kef4ke", out)
        self.assertIn("[REDACTED", out)

    def test_apify_and_supabase(self):
        out = redact_text(f"{FAKE_APIFY} then {FAKE_SUPABASE}")
        self.assertNotIn(FAKE_APIFY, out)
        self.assertNotIn(FAKE_SUPABASE, out)
        self.assertIn("[REDACTED:apify-token]", out)
        self.assertIn("[REDACTED:supabase-token]", out)

    def test_long_opaque_token(self):
        out = redact_text(f"session id {FAKE_OPAQUE} noted")
        self.assertNotIn(FAKE_OPAQUE, out)
        self.assertIn("[REDACTED:opaque]", out)

    def test_env_style_assignment(self):
        out = redact_text("OPENROUTER_API_KEY=supersecretvalue")
        self.assertNotIn("supersecretvalue", out)
        self.assertIn("OPENROUTER_API_KEY=", out)
        self.assertIn("[REDACTED:env]", out)

    def test_yaml_style_secret_key(self):
        out = redact_text("telegram_bot_token: shortvalue")
        self.assertNotIn("shortvalue", out)
        self.assertIn("[REDACTED:env]", out)

    def test_uuid_survives(self):
        uid = "123e4567-e89b-12d3-a456-426614174000"
        out = redact_text(f"job {uid} ran")
        self.assertIn(uid, out)

    def test_plain_text_untouched(self):
        text = "cron scheduler running, 8 jobs enabled, next run 06:00"
        self.assertEqual(redact_text(text), text)

    def test_empty(self):
        self.assertEqual(redact_text(""), "")


class TestRedactObj(unittest.TestCase):
    def test_nested_structures(self):
        obj = {
            "jobs": [{"name": "ok job", "note": f"uses {FAKE_SK}"}],
            "api_key": "plainvalue",
            "level": 3,
        }
        out = redact_obj(obj)
        self.assertNotIn(FAKE_SK, str(out))
        self.assertEqual(out["api_key"], "[REDACTED:key-name]")
        self.assertEqual(out["level"], 3)
        self.assertIn("ok job", out["jobs"][0]["name"])

    def test_secretish_key_masked_even_if_value_benign(self):
        out = redact_obj({"password": "hunter2"})
        self.assertEqual(out["password"], "[REDACTED:key-name]")


class TestContainsSecret(unittest.TestCase):
    def test_detects_and_clears(self):
        dirty = f"key {FAKE_SK} here"
        self.assertTrue(contains_secret(dirty))
        self.assertFalse(contains_secret(redact_text(dirty)))

    def test_clean_text(self):
        self.assertFalse(contains_secret("gateway running, all clear"))


if __name__ == "__main__":
    unittest.main()

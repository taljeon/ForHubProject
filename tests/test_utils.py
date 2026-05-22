from __future__ import annotations

import unittest

from app.utils import (
    normalize_navigation_url,
    normalize_optional_date,
    normalize_priority,
    parse_env_csv,
    parse_env_flag,
)


class UtilsTestCase(unittest.TestCase):
    def test_parse_env_flag(self) -> None:
        self.assertTrue(parse_env_flag("1"))
        self.assertTrue(parse_env_flag("true"))
        self.assertFalse(parse_env_flag("0", default=True))
        self.assertFalse(parse_env_flag(None))

    def test_parse_env_csv(self) -> None:
        self.assertEqual(parse_env_csv("127.0.0.1, localhost"), ("127.0.0.1", "localhost"))
        self.assertEqual(parse_env_csv(None, default=("localhost",)), ("localhost",))

    def test_normalize_navigation_url(self) -> None:
        self.assertEqual(normalize_navigation_url("https://example.com/path"), "https://example.com/path")
        self.assertIsNone(normalize_navigation_url("javascript:alert(1)"))
        self.assertIsNone(normalize_navigation_url("/relative/path"))

    def test_normalize_optional_date(self) -> None:
        self.assertEqual(normalize_optional_date("2026-05-22"), "2026-05-22")
        self.assertIsNone(normalize_optional_date(""))
        with self.assertRaises(ValueError):
            normalize_optional_date("2026/05/22")

    def test_normalize_priority(self) -> None:
        self.assertEqual(normalize_priority(3), 3)
        with self.assertRaises(ValueError):
            normalize_priority(0)


if __name__ == "__main__":
    unittest.main()

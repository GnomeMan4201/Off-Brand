import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from sanitize import defang_domain, defang_url, sanitize_text, validate_public_record_url


class TestSanitize(unittest.TestCase):
    def test_defang_url_https_and_http(self):
        self.assertEqual(
            defang_url("https://evil.example.com/login?a=1"),
            "hxxps://evil[.]example[.]com/login?a=1",
        )
        self.assertEqual(
            defang_url("http://192.0.2.1/phish"),
            "hxxp://192[.]0[.]2[.]1/phish",
        )

    def test_reject_dangerous_schemes(self):
        self.assertIsNone(defang_url("javascript:alert(1)"))
        self.assertIsNone(defang_url("data:text/html,<script>alert(1)</script>"))

    def test_strip_bidi_and_control_chars(self):
        dirty = "PayPal\u202eLogin\x00\u200b"
        self.assertEqual(sanitize_text(dirty), "PayPalLogin")

    def test_defang_domain(self):
        self.assertEqual(defang_domain("allegro.top"), "allegro[.]top")

    def test_validate_public_record_url(self):
        self.assertEqual(
            validate_public_record_url("https://urlscan.io/result/abc/report/"),
            "https://urlscan.io/result/abc/report/",
        )
        self.assertIsNone(validate_public_record_url("https://evil.com/report"))
        self.assertIsNone(validate_public_record_url("http://urlscan.io/result/abc"))


if __name__ == "__main__":
    unittest.main()

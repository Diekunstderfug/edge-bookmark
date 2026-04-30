import unittest

from bookmark_advisor.utils import normalize_url, tokenize


class UtilsTest(unittest.TestCase):
    def test_normalize_url_strips_tracking_parameters(self):
        url = "https://example.com/docs/?utm_source=x&ref=foo&id=1#top"
        self.assertEqual(normalize_url(url), "https://example.com/docs?id=1")

    def test_tokenize_keeps_meaningful_cjk_and_ascii_tokens(self):
        tokens = tokenize("北京大学统一身份认证 ChatGPT login page")
        self.assertIn("北京大学统一身份认证", tokens)
        self.assertIn("chatgpt", tokens)
        self.assertNotIn("login", tokens)


if __name__ == "__main__":
    unittest.main()

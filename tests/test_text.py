"""Tests for the linkify text helper used in note history rendering."""
import unittest

from markupsafe import Markup

from memo.text import linkify


class LinkifyTest(unittest.TestCase):
    def test_bare_url_becomes_anchor(self):
        url = 'https://www.youtube.com/watch?v=ftP5HeOvsl0&list=PLGz&index=1'
        html = str(linkify(url))
        # Ampersands are HTML-escaped inside the attribute (browsers decode them).
        self.assertIn('href="https://www.youtube.com/watch?v=ftP5HeOvsl0&amp;list=PLGz&amp;index=1"', html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertTrue(html.startswith('<a '))

    def test_surrounding_text_preserved_and_escaped(self):
        html = str(linkify('see <b> https://example.com now'))
        self.assertIn('see &lt;b&gt; ', html)
        self.assertIn('<a href="https://example.com"', html)
        self.assertTrue(html.rstrip().endswith(' now'))

    def test_trailing_punctuation_not_part_of_link(self):
        html = str(linkify('visit https://example.com.'))
        self.assertIn('href="https://example.com"', html)
        self.assertTrue(html.endswith('.'))
        self.assertNotIn('example.com."', html)

    def test_non_http_scheme_is_not_linked(self):
        html = str(linkify('run javascript:alert(1) now'))
        self.assertNotIn('<a', html)
        self.assertIn('javascript:alert(1)', html)

    def test_plain_text_is_escaped_without_links(self):
        self.assertEqual(str(linkify('a & b < c')), 'a &amp; b &lt; c')

    def test_empty_returns_empty_markup(self):
        self.assertEqual(linkify(''), Markup(''))
        self.assertEqual(linkify(None), Markup(''))


if __name__ == '__main__':
    unittest.main()

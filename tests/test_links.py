"""Addresses written in a description, made pressable.

A description is somebody else's writing arriving as plain text, and Qt will
only report a press on an address if the words are given to it as markup. So
the words become markup here, which brings two obligations that are the whole
of why this is not a one line regular expression: everything that is NOT an
address has to be escaped, or an ampersand in a title disappears, and every
newline has to become a break, because the format Qt draws collapses runs of
whitespace and a description written in paragraphs would arrive as one line.
"""

import unittest

from weave.format import linked


class WhatBecomesAnAddress(unittest.TestCase):
    def test_one_written_in_full(self):
        self.assertEqual(linked("see https://example.com now"),
                         'see <a href="https://example.com">https://example.com</a> now')

    def test_one_that_leaves_the_scheme_to_be_assumed(self):
        """Plenty of descriptions are written this way. The scheme is added
        for the browser and left out of what is drawn, which is what the
        person wrote."""
        self.assertEqual(linked("go to www.example.com"),
                         'go to <a href="https://www.example.com">www.example.com</a>')

    def test_several_in_one_description(self):
        said = linked("a http://one.test and b https://two.test")
        self.assertEqual(said.count("<a href="), 2)
        self.assertIn(">http://one.test</a>", said)
        self.assertIn(">https://two.test</a>", said)

    def test_a_query_string_survives_whole(self):
        """The ampersands in it are escaped in both halves, because both are
        read as markup."""
        self.assertEqual(
            linked("https://x.test/w?v=abc&t=90"),
            '<a href="https://x.test/w?v=abc&amp;t=90">https://x.test/w?v=abc&amp;t=90</a>')

    def test_nothing_at_all(self):
        self.assertEqual(linked(""), "")

    def test_words_with_no_address_in_them(self):
        self.assertEqual(linked("just some words"), "just some words")


class WhereASentenceEndsAndTheAddressDoes(unittest.TestCase):
    def test_a_full_stop_is_not_part_of_it(self):
        self.assertEqual(linked("see https://example.com."),
                         'see <a href="https://example.com">https://example.com</a>.')

    def test_nor_is_a_comma_or_the_rest(self):
        for mark in (",", ";", ":", "!", "?"):
            self.assertTrue(linked(f"https://x.test{mark}").endswith(f"</a>{mark}"), mark)

    def test_a_bracket_that_nothing_in_it_opened_is_not_part_of_it(self):
        self.assertEqual(linked("(https://x.test/p)"),
                         '(<a href="https://x.test/p">https://x.test/p</a>)')

    def test_but_a_matched_pair_inside_it_is(self):
        """Real addresses carry them, and trimming one would give a browser
        an address that is not the one that was written."""
        self.assertIn(">https://x.test/a_(b)</a>", linked("https://x.test/a_(b)"))


class WhatIsNotAnAddressIsEscaped(unittest.TestCase):
    def test_the_three_characters_that_would_be_read_as_markup(self):
        self.assertEqual(linked("a < b & c > d"), "a &lt; b &amp; c &gt; d")

    def test_around_an_address_as_well(self):
        self.assertEqual(linked("<b> https://x.test <i>"),
                         '&lt;b&gt; <a href="https://x.test">https://x.test</a> &lt;i&gt;')

    def test_so_nothing_written_in_a_description_can_become_a_tag(self):
        """Somebody who writes a tag into a description gets the characters
        they typed, drawn. The address inside it is still an address, and it
        is the only thing in the line that can be pressed."""
        said = linked('<a href="https://evil.test">press me</a>')
        self.assertIn("&lt;a href=", said)
        self.assertIn("&lt;/a&gt;", said)
        self.assertEqual(said.count("<a href="), 1)
        self.assertIn("&gt;press me&lt;", said)


class TheShapeOfTheParagraphSurvives(unittest.TestCase):
    def test_a_newline_becomes_a_break(self):
        """The format Qt draws collapses runs of whitespace, so without this
        a description written in paragraphs arrives as one long line."""
        self.assertEqual(linked("one\ntwo"), "one<br>two")

    def test_including_between_two_addresses(self):
        self.assertIn("</a><br><a href=", linked("https://a.test\nhttps://b.test"))


class TheBrowserIsOnlyEverGivenAnAddress(unittest.TestCase):
    """The markup is built from http and https alone, so nothing else can
    reach here by the front door. The guard is for the back one: what is
    handed to the desktop is acted on by whatever is registered for it."""

    def setUp(self):
        from weave.ui import bridge as module

        self.opened = []
        self.was = module.QDesktopServices.openUrl
        module.QDesktopServices.openUrl = lambda url: self.opened.append(url.toString())
        self.module = module
        self.addCleanup(self.restore)

    def restore(self):
        self.module.QDesktopServices.openUrl = self.was

    def open(self, address):
        bridge = self.module.Bridge.__new__(self.module.Bridge)
        bridge._set_status = lambda *_a, **_k: None
        self.module.Bridge.openLink(bridge, address)
        return self.opened

    def test_an_ordinary_address_is_opened(self):
        self.assertEqual(self.open("https://example.com/a"), ["https://example.com/a"])

    def test_and_a_plain_one(self):
        self.assertEqual(self.open("http://example.com"), ["http://example.com"])

    def test_a_file_is_not(self):
        self.assertEqual(self.open("file:///etc/passwd"), [])

    def test_nor_is_anything_the_desktop_would_run(self):
        for address in ("javascript:alert(1)", "mailto:someone@example.com",
                        "ssh://box/", "", "not an address at all"):
            self.assertEqual(self.open(address), [], address)


if __name__ == "__main__":
    unittest.main()

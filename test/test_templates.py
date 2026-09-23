"""Boolean template algebra is included in normal test discovery."""
from itertools import product
from unittest import TestCase
from pcrscript.templates import BooleanTemplate


class TemplateTests(TestCase):
    def test_boolean_truth_tables(self):
        for left, right in product((False, True), repeat=2):
            with self.subTest(left=left, right=right):
                a, b = BooleanTemplate(left), BooleanTemplate(right)
                self.assertEqual((a & b).match(None), left and right)
                self.assertEqual((a | b).match(None), left or right)

    def test_nested_composition(self):
        template = BooleanTemplate(False) & (BooleanTemplate(False) | BooleanTemplate(True))
        self.assertFalse(template.match(None))

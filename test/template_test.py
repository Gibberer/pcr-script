import unittest
import sys
sys.path.insert(0,'.')
from pcrscript.templates import *

class TestTemplate(unittest.TestCase):
    
    def test_and_true_false(self):
        andTemplate = BooleanTemplate(True) & BooleanTemplate(False)
        self.assertFalse(andTemplate.match(None))
    
    def test_and_true_true(self):
        andTemplate = BooleanTemplate(True) & BooleanTemplate(True)
        self.assertTrue(andTemplate.match(None))
    
    def test_and_false_false(self):
        andTemplate = BooleanTemplate(False) & BooleanTemplate(False)
        self.assertFalse(andTemplate.match(None))
    
    def test_or_true_false(self):
        orTemplate = BooleanTemplate(True) | BooleanTemplate(False)
        self.assertTrue(orTemplate.match(None))
    
    def test_or_true_true(self):
        orTemplate = BooleanTemplate(True) | BooleanTemplate(True)
        self.assertTrue(orTemplate.match(None))
    
    def test_or_false_false(self):
        orTemplate = BooleanTemplate(False) | BooleanTemplate(False)
        self.assertFalse(orTemplate.match(None))
    
    def test_composite(self):
        template = BooleanTemplate(False) & (BooleanTemplate(False) | BooleanTemplate(True))
        self.assertFalse(template.match(None))


if __name__ == '__main__':
    unittest.main()
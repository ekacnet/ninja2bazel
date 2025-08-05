import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cppfileparser import parseIncludes

class TestParseIncludes(unittest.TestCase):
    def test_single_include(self):
        self.assertEqual(parseIncludes('-I/path'), ['/path'])

    def test_multiple_includes(self):
        inc = '-I/path/one -I/path/two'
        self.assertEqual(parseIncludes(inc), ['/path/one', '/path/two'])

    def test_with_spaces(self):
        inc = '-I/with\\ space -I/with\\tspace'
        self.assertEqual(parseIncludes(inc), ['/with\\ space', '/with\\tspace'])

    def test_no_includes(self):
        self.assertEqual(parseIncludes(''), [])

if __name__ == '__main__':
    unittest.main()

import unittest
from parser import parse_manually_generated

class TestParserUtils(unittest.TestCase):
    def test_parse_manual(self):
        res = parse_manually_generated(['a=b', 'c=d'])
        self.assertEqual(res, {'a': 'b', 'c': 'd'})

    def test_bad_format(self):
        with self.assertRaises(SystemExit):
            parse_manually_generated(['oops'])

if __name__ == '__main__':
    unittest.main()

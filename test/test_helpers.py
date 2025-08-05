import unittest
from helpers import resolvePath

class TestResolvePath(unittest.TestCase):
    def test_resolve_path(self):
        self.assertEqual(resolvePath('/a/../b/./c'), '/b/c')
        self.assertEqual(resolvePath('foo/./bar/../baz'), 'foo/baz')

if __name__ == '__main__':
    unittest.main()

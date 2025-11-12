import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from build import Build, BuildTarget, Rule


class TestBuildResolveName(unittest.TestCase):
    def setUp(self):
        out = BuildTarget('out', ('out', None))
        self.build = Build([out], Rule('dummy'), [], [])
        self.build.vars = {'SRC': 'main.c', 'OBJ': 'main.o'}
        self.template = 'gcc -c $SRC -o $OBJ'

    def test_resolve_name_without_exceptvars(self):
        resolved = self.build._resolveName(self.template)
        self.assertEqual(resolved, 'gcc -c main.c -o main.o')

    def test_resolve_name_with_exceptvars(self):
        resolved = self.build._resolveName(self.template, ['OBJ'])
        self.assertEqual(resolved, 'gcc -c main.c -o $OBJ')


if __name__ == '__main__':
    unittest.main()

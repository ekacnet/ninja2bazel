import os
import tempfile
import unittest
from cc_import_parse import cleanupVar, match_glob, parse_glob, parseCCImports

class TestCCImportParseUtils(unittest.TestCase):
    def test_cleanup_var(self):
        self.assertEqual(cleanupVar('"foo"'), 'foo')

    def test_match_glob(self):
        self.assertTrue(match_glob('glob(["*.h"])'))
        self.assertFalse(match_glob('no_glob'))

    def test_parse_glob(self):
        with tempfile.TemporaryDirectory() as td:
            fname = os.path.join(td, 'a.h')
            with open(fname, 'w'):
                pass
            pattern = f'{td}/*.h'
            res = parse_glob(f'glob(["{pattern}"])')
            self.assertIn(fname, res)

    def test_parse_cc_imports(self):
        lines = [
            'cc_import(',
            'name = "foo"',
            'hdrs = ["foo.h"]',
            'deps = [":dep"]',
            ')',
            'cc_import(',
            'name = "dep"',
            ')',
        ]
        res = parseCCImports(lines, 'src')
        names = {imp.name for imp in res}
        self.assertEqual(names, {'foo', 'dep'})
        foo = next(i for i in res if i.name == 'foo')
        self.assertTrue(any(d.name == 'dep' for d in foo.deps))

if __name__ == '__main__':
    unittest.main()

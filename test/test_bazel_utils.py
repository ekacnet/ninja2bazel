import unittest
from bazel import (
    BazelCCImport,
    BazelTarget,
    _getPrefix,
    compare_deps,
    compare_imports,
    findCommonPaths,
    globifyPath,
)

class DummyTarget(BazelTarget):
    pass

class TestBazelUtils(unittest.TestCase):
    def test_get_prefix(self):
        t1 = BazelTarget('cc_library', 'foo', 'src')
        self.assertEqual(_getPrefix(t1, 'src'), '')
        t2 = BazelTarget('cc_library', 'bar', 'lib')
        self.assertEqual(_getPrefix(t2, 'src'), '//lib')
        t3 = BazelTarget('cc_library', 'ext', '@ext//')
        self.assertEqual(_getPrefix(t3, 'src'), '@ext//')

    def test_compare_deps(self):
        a = BazelTarget('cc_library', 'a', 'src')
        b = BazelTarget('cc_library', 'b', 'src')
        cmp = compare_deps(a, b, lambda x: _getPrefix(x, 'src'))
        self.assertLess(cmp, 0)
        self.assertGreater(compare_deps(b, a, lambda x: _getPrefix(x, 'src')), 0)

    def test_compare_imports(self):
        self.assertEqual(compare_imports('load("@a//:foo")', 'load("@a//:foo")'), 0)
        self.assertLess(compare_imports('load("@a//:foo")', 'load("@b//:bar")'), 0)
        self.assertGreater(compare_imports('load("@b//:bar")', 'load("@a//:foo")'), 1-1)

    def test_find_common_paths(self):
        paths = [
            '/a/b/c.h',
            '/a/b/d.h',
        ]
        self.assertEqual(findCommonPaths(paths), ['/a/b'])
        paths = ['/a/x/c.h', '/a/y/d.h']
        res = findCommonPaths(paths)
        self.assertEqual(set(res), {'/a/x', '/a/y'})

    def test_globify_path(self):
        self.assertEqual(globifyPath('src', 'h'), 'src/**/*.h')

    def test_cc_import_as_bazel(self):
        imp = BazelCCImport('foo')
        imp.setHdrs(['/foo.h'])
        imp.setLocation('src')
        res = imp.asBazel({})
        self.assertIn('foo', res)
        self.assertIn('raw_foo', res)
        self.assertTrue(any('cc_import(' in line for line in res['raw_foo']))

if __name__ == '__main__':
    unittest.main()

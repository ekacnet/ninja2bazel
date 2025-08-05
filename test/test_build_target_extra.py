import unittest
from build import BuildTarget, Build, Rule

class TestBuildTargetExtra(unittest.TestCase):
    def test_usage_methods(self):
        out = BuildTarget('out', ('out', None))
        dep = BuildTarget('dep', ('dep', None))
        build = Build([out], Rule('cc'), [dep], [])
        self.assertTrue(dep.isUsedBy(['out']))
        self.assertTrue(dep.isOnlyUsedBy(['out']))
        out2 = BuildTarget('out2', ('out2', None))
        Build([out2], Rule('cc'), [dep], [])
        self.assertTrue(dep.isUsedBy(['out']))
        self.assertFalse(dep.isOnlyUsedBy(['out']))

    def test_deps_are_virtual(self):
        dep = BuildTarget('vdep', ('vdep', None))
        # No producer and not a file -> virtual
        self.assertTrue(dep.depsAreVirtual())
        dep.markAsExternal()
        self.assertFalse(dep.depsAreVirtual())
        dep.markAsFile()
        self.assertFalse(dep.depsAreVirtual())

if __name__ == '__main__':
    unittest.main()

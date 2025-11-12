import unittest
from build import BuildTarget, Build, Rule


class TestBuildTargetUsage(unittest.TestCase):
    def test_no_users(self):
        dep = BuildTarget('dep', ('dep', None))
        self.assertFalse(dep.isUsedBy(['out']))
        self.assertFalse(dep.isOnlyUsedBy(['out']))

    def test_partial_users(self):
        dep = BuildTarget('dep', ('dep', None))
        out1 = BuildTarget('out1', ('out1', None))
        Build([out1], Rule('cc'), [dep], [])
        self.assertTrue(dep.isUsedBy(['out1']))
        self.assertTrue(dep.isOnlyUsedBy(['out1']))
        out2 = BuildTarget('out2', ('out2', None))
        Build([out2], Rule('cc'), [dep], [])
        self.assertTrue(dep.isUsedBy(['out1']))
        self.assertFalse(dep.isOnlyUsedBy(['out1']))

    def test_deps_are_virtual(self):
        virt = BuildTarget('virt', ('virt', None))
        Build([virt], Rule('phony'), [], [])
        out = BuildTarget('out', ('out', None))
        Build([out], Rule('cc'), [], [virt])
        self.assertTrue(out.depsAreVirtual())

        real = BuildTarget('real', ('real', None))
        Build([real], Rule('cc'), [], [])
        out2 = BuildTarget('out2', ('out2', None))
        Build([out2], Rule('cc'), [], [real])
        self.assertFalse(out2.depsAreVirtual())


if __name__ == '__main__':
    unittest.main()

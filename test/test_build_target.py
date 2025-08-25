import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from build import BuildTarget, Rule, Build


class TestBuildTarget(unittest.TestCase):
    def test_basic_attributes(self):
        bt = BuildTarget("foo", ("foo", None))
        self.assertEqual(bt.name, "foo")
        self.assertEqual(bt.shortName, "foo")
        self.assertFalse(bt.implicit)

    def test_mark_as_file_and_top_level(self):
        bt = BuildTarget("foo", ("foo", None))
        bt.markAsFile()
        bt.markTopLevel()
        self.assertTrue(bt.is_a_file)
        self.assertTrue(bt.topLevel)

    def test_is_only_used_by(self):
        bt = BuildTarget("foo", ("foo", None))
        out1 = BuildTarget("out1", ("out1", None))
        Build([out1], Rule("phony"), [bt], [])
        self.assertTrue(bt.isOnlyUsedBy(["out1"]))


if __name__ == "__main__":
    unittest.main()

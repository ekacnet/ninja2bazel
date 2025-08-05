import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bazel import BazelTarget, ExportedFile

class TestBazelTarget(unittest.TestCase):
    def test_as_bazel_binary(self):
        b = BazelTarget('cc_binary', 'app', 'src')
        b.addSrc(ExportedFile('main.cpp', 'src'))
        res = b.asBazel({})
        expected = {
            'app': [
                'cc_binary(',
                '    name = "app",',
                '    srcs = [',
                '        ":main.cpp",',
                '    ],',
                '    linkopts = [',
                '    ],',
                '    visibility = ["//visibility:public"],',
                ')'
            ]
        }
        self.assertEqual(res, expected)

if __name__ == '__main__':
    unittest.main()

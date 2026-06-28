import importlib.machinery
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
POSTPROCESS_PATH = REPO_ROOT / "postprocess"


loader = importlib.machinery.SourceFileLoader("postprocess", str(POSTPROCESS_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
postprocess = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = postprocess
loader.exec_module(postprocess)


class TestPostprocess(unittest.TestCase):
    def test_load_lines_preserves_multiline_load_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            build_file = Path(tmpdir) / "BUILD.bazel"
            build_file.write_text(
                "\n".join(
                    [
                        'load("@rules_cc//cc:defs.bzl", "cc_binary")',
                        "load(",
                        '    "@com_google_protobuf//bazel:cc_proto_library.bzl",',
                        '    "cc_proto_library",',
                        ")",
                        "",
                        "cc_binary(",
                        '    name = "app",',
                        ")",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                postprocess.load_lines(str(build_file)),
                [
                    'load("@rules_cc//cc:defs.bzl", "cc_binary")',
                    "load(",
                    '    "@com_google_protobuf//bazel:cc_proto_library.bzl",',
                    '    "cc_proto_library",',
                    ")",
                ],
            )


if __name__ == "__main__":
    unittest.main()

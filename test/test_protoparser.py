import tempfile
import unittest
from pathlib import Path

from protoparser import cache as proto_cache, findProtoIncludes, seen as proto_seen


class TestProtoParser(unittest.TestCase):
    def tearDown(self) -> None:
        proto_cache.clear()
        proto_seen.clear()

    def test_find_proto_includes_resolves_and_caches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            dep = base / "dep.proto"
            dep.write_text("message Dep {}")
            root = base / "root.proto"
            root.write_text(
                'import "dep.proto";\nimport "google/api/annotations.proto";\n'
            )
            res1 = findProtoIncludes(str(root), [str(base)])
            self.assertIn((str(dep), str(base)), res1[str(root)])
            self.assertIn(("google/api/annotations.proto", "@"), res1[str(root)])
            res2 = findProtoIncludes(str(root), [str(base)])
            self.assertIs(res1, res2)

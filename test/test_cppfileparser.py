import tempfile
import unittest
from pathlib import Path

from bazel import BazelCCImport
from build import BuildTarget
from cppfileparser import (
    findAllHeaderFiles,
    parseIncludes,
    _findCPPIncludeForFileSameDir,
    _findCPPIncludeForFile,
    findCPPIncludes,
)
from helpers import resolvePath


class TestCPPFileParser(unittest.TestCase):
    def test_find_all_header_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            h1 = tmp_path / "a.h"
            h1.write_text("")
            sub = tmp_path / "sub"
            sub.mkdir()
            h2 = sub / "b.hpp"
            h2.write_text("")
            headers = list(findAllHeaderFiles(str(tmp_path)))
            self.assertIn(resolvePath(str(h1)), headers)
            self.assertIn(resolvePath(str(h2)), headers)

    def test_parse_includes_dedup(self) -> None:
        res = parseIncludes("-Ifoo -isystem bar -Ifoo")
        self.assertEqual(res, ["foo", "bar"])

    def test_find_cpp_include_same_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            main = tmp_path / "main.cpp"
            main.write_text("#include \"hdr.h\"\n")
            hdr = tmp_path / "hdr.h"
            hdr.write_text("")
            found, inc = _findCPPIncludeForFileSameDir(
                str(main),
                "hdr.h",
                [],
                str(tmp_path),
                [],
                [],
                {},
                None,
                False,
                "/work",
                str(tmp_path),
            )
            self.assertTrue(found)
            self.assertIn((resolvePath(str(hdr)), None), inc.foundHeaders)

    def test_find_cpp_include_with_cc_import(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            include_dir = tmp_path / "include"
            include_dir.mkdir()
            hdr = include_dir / "import.h"
            hdr.write_text("")
            cc_imp = BazelCCImport("imp")
            cc_imp.hdrs = [resolvePath(str(hdr))]
            imp_target = BuildTarget("imp", ("imp", None)).setOpaque(cc_imp)
            found, inc = _findCPPIncludeForFile(
                "import.h",
                ["/no"],
                str(tmp_path),
                [imp_target],
                [str(include_dir)],
                {},
                None,
                "/work",
                str(tmp_path),
            )
            self.assertTrue(found)
            self.assertIn(imp_target, inc.neededImports)

    def test_find_cpp_includes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "local.h"
            local.write_text("")
            include_dir = root / "include"
            include_dir.mkdir()
            other = include_dir / "other.h"
            other.write_text("")
            cpp = root / "main.cpp"
            cpp.write_text(
                '#include "local.h"\n#include <other.h>\n#include "missing.h"\n'
            )
            result = findCPPIncludes(
                str(cpp),
                ["include"],
                [],
                [],
                {},
                False,
                None,
                "/work",
                srcDir=str(root),
            )
            self.assertIn((resolvePath(str(local)), None), result.foundHeaders)
            self.assertIn(
                (resolvePath(str(other)), "include"),
                result.foundHeaders,
            )
            self.assertIn("missing.h", result.notFoundHeaders)


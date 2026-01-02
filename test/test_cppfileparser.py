import tempfile
import unittest
from pathlib import Path

from bazel import BazelCCImport
from build import BuildTarget
from cppfileparser import (
    _findCPPIncludeForFile,
    _findCPPIncludeForFileSameDir,
    cache as cpp_cache,
    findAllHeaderFiles,
    findCPPIncludes,
    parseIncludes,
    seen as cpp_seen,
)
from helpers import resolvePath


class TestParseIncludes(unittest.TestCase):
    def test_single_include(self):
        self.assertEqual(parseIncludes("-I/path"), ["/path"])

    def test_multiple_includes(self):
        inc = "-I/path/one -I/path/two"
        self.assertEqual(parseIncludes(inc), ["/path/one", "/path/two"])

    def test_with_spaces(self):
        inc = "-I/with\\ space -I/with\\tspace"
        self.assertEqual(parseIncludes(inc), ["/with\\ space", "/with\\tspace"])

    def test_no_includes(self):
        self.assertEqual(parseIncludes(""), [])


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


class TestCPPGeneratedHeaders(unittest.TestCase):
    def tearDown(self) -> None:
        cpp_cache.clear()
        cpp_seen.clear()

    def test_generated_header_paths_are_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            gen_dir = Path(td)
            main = gen_dir / "gen.h"
            main.write_text('#include "nested.h"\n')
            nested = gen_dir / "nested.h"
            nested.write_text("")

            generated_files = {
                "gen.h": (None, str(gen_dir)),
                "nested.h": (None, str(gen_dir)),
            }

            found, includes = _findCPPIncludeForFile(
                "gen.h",
                ["/generated"],
                str(gen_dir),
                [],
                [],
                generated_files,
                str(gen_dir),
                str(gen_dir),
                str(gen_dir),
            )
            self.assertTrue(found)
            self.assertIn(("gen.h", "/generated"), includes.neededGeneratedFiles)
            self.assertIn(("nested.h", "/generated"), includes.neededGeneratedFiles)

            result = findCPPIncludes(
                str(main),
                ["/generated"],
                [],
                [],
                generated_files,
                True,
                str(gen_dir),
                str(gen_dir),
                str(gen_dir),
            )
            self.assertIn("nested.h", {h[0] for h in result.neededGeneratedFiles})

    def test_not_found_filters_pb_headers_and_uses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            file = root / "main.cpp"
            file.write_text('#include "missing.pb.h"\n#include "other_missing.h"\n')

            first = findCPPIncludes(
                str(file),
                ["inc"],
                [],
                [],
                {},
                False,
                None,
                td,
                td,
            )
            self.assertNotIn("missing.pb.h", first.notFoundHeaders)
            self.assertIn("other_missing.h", first.notFoundHeaders)
            second = findCPPIncludes(
                str(file),
                [],
                [],
                [],
                {},
                False,
                None,
                td,
                td,
            )
            self.assertIs(first, second)

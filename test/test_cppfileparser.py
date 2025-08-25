import os
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


def test_find_all_header_files(tmp_path):
    h1 = tmp_path / "a.h"
    h1.write_text("")
    sub = tmp_path / "sub"
    sub.mkdir()
    h2 = sub / "b.hpp"
    h2.write_text("")
    headers = list(findAllHeaderFiles(str(tmp_path)))
    assert resolvePath(str(h1)) in headers
    assert resolvePath(str(h2)) in headers


def test_parse_includes_dedup():
    res = parseIncludes("-Ifoo -isystem bar -Ifoo")
    assert res == ["foo", "bar"]


def test_find_cpp_include_same_dir(tmp_path):
    main = tmp_path / "main.cpp"
    main.write_text("#include \"hdr.h\"\\n")
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
    assert found
    assert (resolvePath(str(hdr)), None) in inc.foundHeaders


def test_find_cpp_include_with_cc_import(tmp_path):
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
    assert found
    assert imp_target in inc.neededImports


def test_find_cpp_includes(tmp_path):
    root = tmp_path
    local = root / "local.h"
    local.write_text("")
    include_dir = root / "include"
    include_dir.mkdir()
    other = include_dir / "other.h"
    other.write_text("")
    cpp = root / "main.cpp"
    cpp.write_text(
        '#include "local.h"\n#include <other.h>\n#include "missing.h"\n',
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
    assert (resolvePath(str(local)), None) in result.foundHeaders
    assert (
        resolvePath(str(other)),
        "include",
    ) in result.foundHeaders
    assert "missing.h" in result.notFoundHeaders

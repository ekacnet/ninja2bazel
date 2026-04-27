import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bazel import BazelBuild, BazelGenRuleTarget, BazelTarget
from build import BazelBuildVisitorContext, Build, BuildTarget, TopLevelGroupingStrategy
from configure_file import find_configure_file, parse_configure_files_list, parse_configure_vars


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDERER = os.path.join(ROOT, "contrib", "posttreatments", "render_configure_file.py")


class TestConfigureFile(unittest.TestCase):
    def test_parse_configure_files_list_finds_value_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            build = Path(td) / "build"
            flow = root / "flow"
            root.mkdir()
            flow.mkdir()
            build.mkdir()
            (flow / "ProtocolVersion.h.cmake").write_text("#define V @VERSION@\n")
            (flow / "ProtocolVersions.cmake").write_text('set(VERSION "1")\n')
            list_file = Path(td) / "configure_files.txt"
            list_file.write_text(
                "configure_file(${CMAKE_CURRENT_SOURCE_DIR}/ProtocolVersion.h.cmake "
                "${CMAKE_CURRENT_BINARY_DIR}/include/flow/ProtocolVersion.h)\n"
            )

            parsed = parse_configure_files_list(str(list_file), str(root), str(build))

        self.assertIn("flow/include/flow/ProtocolVersion.h", parsed)
        entry = parsed["flow/include/flow/ProtocolVersion.h"]
        self.assertEqual(entry.source.replace(os.path.sep, "/").split("/")[-1], "ProtocolVersion.h.cmake")
        self.assertIn("/flow/", entry.source.replace(os.path.sep, "/"))
        self.assertEqual(len(entry.value_files), 1)

    def test_parse_configure_files_list_fails_for_missing_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            build = Path(td) / "build"
            root.mkdir()
            build.mkdir()
            (root / "config.h.cmake").write_text("#define V @MISSING@\n")
            list_file = Path(td) / "configure_files.txt"
            list_file.write_text(
                "configure_file(${CMAKE_CURRENT_SOURCE_DIR}/config.h.cmake "
                "${CMAKE_CURRENT_BINARY_DIR}/config.h)\n"
            )

            with self.assertRaises(SystemExit):
                parse_configure_files_list(str(list_file), str(root), str(build))

    def test_parse_configure_files_list_accepts_cli_configure_vars(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            build = Path(td) / "build"
            root.mkdir()
            build.mkdir()
            (root / "config.h.cmake").write_text("#define V @FROM_CLI@\n")
            list_file = Path(td) / "configure_files.txt"
            list_file.write_text(
                "configure_file(${CMAKE_CURRENT_SOURCE_DIR}/config.h.cmake "
                "${CMAKE_CURRENT_BINARY_DIR}/config.h)\n"
            )

            parsed = parse_configure_files_list(
                str(list_file),
                str(root),
                str(build),
                parse_configure_vars(["FROM_CLI=yes"]),
            )

        entry = parsed["config.h"]
        self.assertEqual(entry.value_files, ())
        self.assertEqual(entry.variables, {"FROM_CLI": "yes"})

    def test_parse_configure_files_list_skips_unneeded_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            build = Path(td) / "build"
            root.mkdir()
            build.mkdir()
            (root / "needed.h.cmake").write_text("#define V @VERSION@\n")
            (root / "unused.h.cmake").write_text("#define V @MISSING@\n")
            (root / "values.cmake").write_text("set(VERSION 1)\n")
            list_file = Path(td) / "configure_files.txt"
            list_file.write_text(
                "configure_file(${CMAKE_CURRENT_SOURCE_DIR}/needed.h.cmake "
                "${CMAKE_CURRENT_BINARY_DIR}/include/needed.h)\n"
                "configure_file(${CMAKE_CURRENT_SOURCE_DIR}/unused.h.cmake "
                "${CMAKE_CURRENT_BINARY_DIR}/include/unused.h)\n"
            )

            parsed = parse_configure_files_list(
                str(list_file),
                str(root),
                str(build),
                needed_outputs={"include/needed.h"},
            )

        self.assertIn("include/needed.h", parsed)
        self.assertNotIn("include/unused.h", parsed)

    def test_parse_configure_files_list_uses_cmake_file_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            build = Path(td) / "build"
            flow = root / "flow"
            flow.mkdir(parents=True)
            build.mkdir()
            (flow / "ProtocolVersion.h.cmake").write_text("#define V @VERSION@\n")
            (flow / "ProtocolVersions.cmake").write_text("set(VERSION 1)\n")
            cmake_file = flow / "ProtocolVersion.cmake"
            cmake_file.write_text(
                "configure_file(${CMAKE_CURRENT_SOURCE_DIR}/ProtocolVersion.h.cmake "
                "${CMAKE_CURRENT_BINARY_DIR}/include/flow/ProtocolVersion.h)\n"
            )

            parsed = parse_configure_files_list(
                str(cmake_file),
                str(root),
                str(build),
                needed_outputs={"pregenerated/flow/include/flow/ProtocolVersion.h"},
            )

        self.assertIn("flow/include/flow/ProtocolVersion.h", parsed)
        self.assertIn("/flow/", parsed["flow/include/flow/ProtocolVersion.h"].source)
        self.assertIsNotNone(
            find_configure_file(
                parsed,
                "pregenerated/flow/include/flow/ProtocolVersion.h",
                str(build),
            )
        )

    def test_parse_flat_configure_files_list_infers_directory_from_template(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            build = Path(td) / "build"
            flow = root / "flow"
            flow.mkdir(parents=True)
            build.mkdir()
            (flow / "ProtocolVersion.h.cmake").write_text("#define V @VERSION@\n")
            (flow / "ProtocolVersions.cmake").write_text("set(VERSION 1)\n")
            list_file = root / "configure_list"
            list_file.write_text(
                "configure_file(${CMAKE_CURRENT_SOURCE_DIR}/ProtocolVersion.h.cmake "
                "${CMAKE_CURRENT_BINARY_DIR}/include/flow/ProtocolVersion.h)\n"
            )

            parsed = parse_configure_files_list(
                str(list_file),
                str(root),
                str(build),
                needed_outputs={"pregenerated/flow/include/flow/ProtocolVersion.h"},
            )

        self.assertIn("flow/include/flow/ProtocolVersion.h", parsed)
        self.assertIsNotNone(
            find_configure_file(
                parsed,
                "pregenerated/flow/include/flow/ProtocolVersion.h",
                str(build),
            )
        )

    def test_parse_flat_configure_files_list_infers_current_dir_before_source_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            build = Path(td) / "build"
            bindings = root / "bindings" / "c"
            foundationdb = bindings / "foundationdb"
            foundationdb.mkdir(parents=True)
            build.mkdir()
            (foundationdb / "fdb_c_apiversion.h.cmake").write_text("#define V @VERSION@\n")
            (bindings / "values.cmake").write_text("set(VERSION 1)\n")
            list_file = root / "configure_list"
            list_file.write_text(
                "configure_file(${CMAKE_CURRENT_SOURCE_DIR}/foundationdb/fdb_c_apiversion.h.cmake "
                "${CMAKE_CURRENT_BINARY_DIR}/foundationdb/fdb_c_apiversion.g.h)\n"
            )

            parsed = parse_configure_files_list(
                str(list_file),
                str(root),
                str(build),
                needed_outputs={"pregenerated/bindings/c/foundationdb/fdb_c_apiversion.g.h"},
            )

        self.assertIn("bindings/c/foundationdb/fdb_c_apiversion.g.h", parsed)
        self.assertNotIn("bindings/c/foundationdb/foundationdb/fdb_c_apiversion.g.h", parsed)
        self.assertIsNotNone(
            find_configure_file(
                parsed,
                "pregenerated/bindings/c/foundationdb/fdb_c_apiversion.g.h",
                str(build),
            )
        )

    def test_render_configure_file_uses_multiple_value_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "config.h.cmake"
            values_a = Path(td) / "a.cmake"
            values_b = Path(td) / "b.cmake"
            output = Path(td) / "out" / "config.h"
            template.write_text("#define A @A@\n#define B ${B}\n")
            values_a.write_text("set(A one)\n")
            values_b.write_text("set(B two)\n")

            subprocess.run(
                [sys.executable, RENDERER, str(template), str(output), str(values_a), str(values_b)],
                check=True,
            )

            self.assertEqual(output.read_text(), "#define A one\n#define B two\n")

    def test_render_configure_file_uses_cli_vars(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            template = Path(td) / "config.h.cmake"
            values = Path(td) / "values.cmake"
            output = Path(td) / "out" / "config.h"
            template.write_text("#define A @A@\n#define B @B@\n")
            values.write_text("set(A from-file)\nset(B from-file)\n")

            subprocess.run(
                [
                    sys.executable,
                    RENDERER,
                    str(template),
                    str(output),
                    "--var",
                    "A=from-cli",
                    str(values),
                ],
                check=True,
            )

            self.assertEqual(
                output.read_text(),
                "#define A from-cli\n#define B from-file\n",
            )

    def test_pregenerated_include_gets_configure_file_genrule(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            build_dir = Path(td) / "build"
            pregenerated = build_dir / "pregenerated" / "include" / "flow"
            root.mkdir()
            build_dir.mkdir()
            pregenerated.mkdir(parents=True)
            (root / "ProtocolVersion.h.cmake").write_text("#define V @VERSION@\n")
            (root / "ProtocolVersions.cmake").write_text("set(VERSION 1)\n")
            list_file = Path(td) / "configure_files.txt"
            list_file.write_text(
                "configure_file(${CMAKE_CURRENT_SOURCE_DIR}/ProtocolVersion.h.cmake "
                "${CMAKE_CURRENT_BINARY_DIR}/include/flow/ProtocolVersion.h)\n"
            )
            configure_files = parse_configure_files_list(
                str(list_file),
                str(root),
                str(build_dir),
                parse_configure_vars(["CLI_VALUE=abc"]),
            )
            TopLevelGroupingStrategy("")
            bb = BazelBuild("")
            current = BazelTarget("cc_library", "flow", ".")
            ctx = BazelBuildVisitorContext(
                False,
                f"{root}{os.path.sep}",
                bb,
                [],
                current=current,
                prefix=".",
                configure_files=configure_files,
                configure_binary_dir=str(build_dir),
            )
            el = BuildTarget("flow.cc", ("flow.cc", "."))
            el.setIncludedFiles(
                [
                    (
                        "include/flow/ProtocolVersion.h",
                        f"{build_dir}{os.path.sep}pregenerated{os.path.sep}include{os.path.sep}flow",
                    )
                ]
            )

            Build._handleIncludeBazelTarget(el, ctx, f"{build_dir}{os.path.sep}")
            bb.bazelTargets.add(current)
            content = bb.genBazelBuildContent()["."]

        self.assertIn("genrule(", content)
        self.assertEqual(content.count("genrule("), 1)
        self.assertIn('name = "configure_pregenerated_include_flow_ProtocolVersion_h"', content)
        self.assertIn('":pregenerated/include/flow/ProtocolVersion.h"', content)
        self.assertIn("//contrib/posttreatments:render_configure_file", content)
        self.assertIn("--var CLI_VALUE=abc", content)
        self.assertIn(":pregenerated/include/flow/ProtocolVersion.h", content)
        self.assertTrue(any(isinstance(target, BazelGenRuleTarget) for target in bb.bazelTargets))

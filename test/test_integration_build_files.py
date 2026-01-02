import unittest
import pytest
from pathlib import Path
from unittest import mock
from parser import main as parser_main

import ninjabuild


class TestIntegrationBuildParsing(unittest.TestCase):
    def setUp(self) -> None:
        self.data_dir = Path(__file__).parent / "data"
        self.build_file = self.data_dir / "build.ninja"
        self.raw_ninja = self.build_file.read_text().splitlines(True)

    def _parse_targets(self):
        with mock.patch.object(
            ninjabuild.NinjaParser, "executeGenerator", return_value=None
        ):
            return ninjabuild.getBuildTargets(
                raw_ninja=self.raw_ninja,
                dir=str(self.data_dir),
                ninjaFileName=str(self.build_file),
                manuallyGenerated={},
                codeRootDir=str(self.data_dir),
                directoryPrefix="",
                remap={},
                cc_imports=[],
                compilerIncludes=[],
                top_level_targets=["libLogging.a", "libXarHelperLib.a", "xarexec_fuse"],
            )

    def test_parses_ninja_graph_with_expected_dependencies(self):
        top_levels = self._parse_targets()
        self.assertSetEqual(
            {t.name for t in top_levels},
            {"libLogging.a", "libXarHelperLib.a", "xarexec_fuse"},
        )

        lib_logging = next(t for t in top_levels if t.name == "libLogging.a")
        self.assertIsNotNone(lib_logging.producedby)
        self.assertEqual(
            lib_logging.producedby.rulename.name, "CXX_STATIC_LIBRARY_LINKER__Logging_"
        )

        logging_objects = {
            i.name: i
            for i in lib_logging.producedby.getInputs()
            if i.name.endswith(".o")
        }
        self.assertIn("CMakeFiles/Logging.dir/xar/Logging.cpp.o", logging_objects)
        obj_target = logging_objects["CMakeFiles/Logging.dir/xar/Logging.cpp.o"]
        self.assertEqual(obj_target.producedby.rulename.name, "CXX_COMPILER__Logging_")
        self.assertIn(
            "/testing/xar/Logging.cpp",
            {i.name for i in obj_target.producedby.getInputs()},
        )

        xarexec = next(t for t in top_levels if t.name == "xarexec_fuse")
        self.assertEqual(
            {d.name for d in xarexec.producedby.depends},
            {"libLogging.a", "libXarHelperLib.a"},
        )

    def test_visiting_graph_generates_bazel_targets(self):
        top_levels = self._parse_targets()
        build_files = ninjabuild.genBazelBuildFiles(
            top_levels, str(self.data_dir), "", "bazel/cpp"
        )

        self.assertIn(".", build_files)
        content = build_files["."]
        self.assertIn('cc_library(\n    name = "Logging"', content)
        self.assertIn('":/testing/xar/Logging.cpp"', content)
        self.assertIn('cc_library(\n    name = "XarHelperLib"', content)
        self.assertIn('":/testing/xar/XarLinux.cpp"', content)
        self.assertIn('cc_binary(\n    name = "xarexec_fuse"', content)
        self.assertIn('":Logging"', content)
        self.assertIn('":XarHelperLib"', content)

    def test_visiting_graph_generates_bazel_targets_from_main_raises(self):
        with pytest.raises(SystemExit) as excinfo:
            parser_main()

        assert excinfo.value.code != 0

    def test_visiting_graph_generates_bazel_targets_from_main(self):
        with mock.patch.object(
            ninjabuild.NinjaParser, "executeGenerator", return_value=None
        ):
            parser_main(["test/data/build.ninja", str(self.data_dir)])

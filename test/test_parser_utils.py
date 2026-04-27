import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from parser import (
    _build_post_treatment_command,
    _configure_vars_from_cli_paths,
    install_configure_file_tool,
    parse_manually_generated,
    run_post_treatments,
)


class TestParserUtils(unittest.TestCase):
    def test_parse_manual(self):
        res = parse_manually_generated(['a=b', 'c=d'])
        self.assertEqual(res, {'a': 'b', 'c': 'd'})

    def test_bad_format(self):
        with self.assertRaises(SystemExit):
            parse_manually_generated(['oops'])

    def test_build_post_treatment_command_for_python_script(self):
        self.assertEqual(
            _build_post_treatment_command("script.py", "foo/BUILD.bazel"),
            [sys.executable, "script.py", "foo/BUILD.bazel"],
        )

    def test_build_post_treatment_command_for_executable(self):
        self.assertEqual(
            _build_post_treatment_command("./script", "foo/BUILD.bazel"),
            ["./script", "foo/BUILD.bazel"],
        )

    def test_configure_vars_from_cli_paths_sets_cmake_dirs(self):
        values = _configure_vars_from_cli_paths(
            "/tmp/project/src",
            "/tmp/project/build",
            ".",
            None,
        )

        self.assertEqual(values["CMAKE_SOURCE_DIR"], "/tmp/project/src")
        self.assertEqual(values["CMAKE_BINARY_DIR"], "/tmp/project/build")

    def test_configure_vars_from_cli_paths_uses_prefix_for_top_level_build(self):
        values = _configure_vars_from_cli_paths(
            "/tmp/project/src",
            "/tmp/project/build",
            "subdir",
            None,
        )

        self.assertEqual(values["CMAKE_SOURCE_DIR"], "/tmp/project/src/subdir")

    def test_configure_vars_from_cli_paths_allows_cli_override(self):
        values = _configure_vars_from_cli_paths(
            "/tmp/project/src",
            "/tmp/project/build",
            ".",
            ["CMAKE_SOURCE_DIR=/override/src", "CUSTOM=yes"],
        )

        self.assertEqual(values["CMAKE_SOURCE_DIR"], "/override/src")
        self.assertEqual(values["CMAKE_BINARY_DIR"], "/tmp/project/build")
        self.assertEqual(values["CUSTOM"], "yes")

    def test_install_configure_file_tool_copies_bazel_package(self):
        with tempfile.TemporaryDirectory() as td:
            install_configure_file_tool(td, ".")

            self.assertTrue(
                (Path(td) / "bazel" / "tools" / "render_configure_file.py").exists()
            )

    @mock.patch("parser.subprocess.run")
    @mock.patch("parser.os.path.exists", return_value=True)
    def test_run_post_treatments_runs_all_scripts(self, _exists, run):
        run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")

        run_post_treatments("out/BUILD.bazel", ["first.py", "./second"])

        self.assertEqual(
            run.call_args_list[0].args[0],
            [sys.executable, "first.py", "out/BUILD.bazel"],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["./second", "out/BUILD.bazel"],
        )

    @mock.patch("parser.subprocess.run")
    @mock.patch("parser.os.path.exists", return_value=True)
    def test_run_post_treatments_fails_on_non_zero_exit(self, _exists, run):
        run.return_value = SimpleNamespace(returncode=4, stdout="", stderr="boom")

        with self.assertRaises(SystemExit):
            run_post_treatments("out/BUILD.bazel", ["first.py"])


if __name__ == "__main__":
    unittest.main()

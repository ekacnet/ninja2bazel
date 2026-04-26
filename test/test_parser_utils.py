import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from parser import (
    _build_post_treatment_command,
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

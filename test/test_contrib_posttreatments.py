import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(
    ROOT,
    "contrib",
    "posttreatments",
    "add_crc32_arm_crc_copts.py",
)
SAMPLECRC = os.path.join(
    ROOT,
    "contrib",
    "posttreatments",
    "examples",
    "BUILD.bazel.addcrc",
)
PROTOCOL_SCRIPT = os.path.join(
    ROOT,
    "contrib",
    "posttreatments",
    "add_protocol_version_header_genrule.py",
)
PROTOCOL_RENDERER = os.path.join(
    ROOT,
    "contrib",
    "posttreatments",
    "render_protocol_version_header.py",
)
PROTOCOL_SAMPLE_DIR = os.path.join(
    ROOT,
    "contrib",
    "posttreatments",
    "examples",
    "protocol_version",
)
PROTOCOL_SAMPLE_BUILD = os.path.join(PROTOCOL_SAMPLE_DIR, "BUILD.bazel")


class TestContribPostTreatments(unittest.TestCase):
    def test_rewrites_crc32_copts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            build_file = os.path.join(tmpdir, "BUILD.bazel")
            shutil.copyfile(SAMPLECRC, build_file)

            subprocess.run([sys.executable, SCRIPT, build_file], check=True)

            with open(build_file, "r") as f:
                content = f.read()

        self.assertIn("name='crc32'", content)
        self.assertIn("name='adler32'", content)
        self.assertIn(
            "copts=['-Wall', '-Wextra'] + select({':platform_linux_arm64': "
            "['-march=armv8-a+crc'], '//conditions:default': []})",
            content,
        )

    def test_second_run_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            build_file = os.path.join(tmpdir, "BUILD.bazel")
            shutil.copyfile(SAMPLECRC, build_file)

            subprocess.run([sys.executable, SCRIPT, build_file], check=True)
            with open(build_file, "r") as f:
                first_pass = f.read()

            subprocess.run([sys.executable, SCRIPT, build_file], check=True)
            with open(build_file, "r") as f:
                second_pass = f.read()

        self.assertEqual(first_pass, second_pass)
        self.assertEqual(second_pass.count("-march=armv8-a+crc"), 1)

    def test_adds_protocol_version_genrule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            build_file = os.path.join(tmpdir, "BUILD.bazel")
            shutil.copyfile(PROTOCOL_SAMPLE_BUILD, build_file)

            subprocess.run([sys.executable, PROTOCOL_SCRIPT, build_file], check=True)

            with open(build_file, "r") as f:
                content = f.read()

        self.assertIn("genrule(", content)
        self.assertIn("name='generate_protocol_version_header'", content)
        self.assertIn(
            "outs=['pregenerated/flow/include/flow/ProtocolVersion.h']",
            content,
        )
        self.assertIn(
            "tools=['//contrib/posttreatments:render_protocol_version_header']",
            content,
        )
        self.assertIn("$(location flow/ProtocolVersion.h.cmake)", content)
        self.assertIn("$(location flow/ProtocolVersions.cmake)", content)

    def test_protocol_genrule_second_run_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            build_file = os.path.join(tmpdir, "BUILD.bazel")
            shutil.copyfile(PROTOCOL_SAMPLE_BUILD, build_file)

            subprocess.run([sys.executable, PROTOCOL_SCRIPT, build_file], check=True)
            with open(build_file, "r") as f:
                first_pass = f.read()

            subprocess.run([sys.executable, PROTOCOL_SCRIPT, build_file], check=True)
            with open(build_file, "r") as f:
                second_pass = f.read()

        self.assertEqual(first_pass, second_pass)
        self.assertEqual(second_pass.count("generate_protocol_version_header"), 1)

    def test_renders_protocol_version_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = os.path.join(tmpdir, "flow")
            shutil.copytree(os.path.join(PROTOCOL_SAMPLE_DIR, "flow"), source_dir)
            output = os.path.join(
                tmpdir,
                "pregenerated",
                "flow",
                "include",
                "flow",
                "ProtocolVersion.h",
            )

            subprocess.run(
                [
                    sys.executable,
                    PROTOCOL_RENDERER,
                    os.path.join(source_dir, "ProtocolVersion.h.cmake"),
                    os.path.join(source_dir, "ProtocolVersions.cmake"),
                    output,
                ],
                check=True,
            )

            with open(output, "r") as f:
                content = f.read()

        self.assertIn('#define DEFAULT_VERSION "0x0FDB00B073000000LL"', content)
        self.assertIn('#define FUTURE_VERSION "0x0FDB00B074000000LL"', content)
        self.assertIn(
            '#define MIN_COMPATIBLE_VERSION "0x0FDB00B070000000LL"',
            content,
        )

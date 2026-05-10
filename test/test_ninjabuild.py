import os
import sys
import tempfile
import unittest
from pathlib import Path

from bazel import BazelCCImport
from build import Build, BuildTarget, Rule
from ninjabuild import (
    NinjaParser,
    _copyFilesBackNForth,
    getToplevels,
    isCPPLikeFile,
    isProtoLikeFile,
)


class TestNinjaBuildUtils(unittest.TestCase):
    def test_is_cpp_like(self):
        for name in ["foo.c", "bar.cc", "baz.cpp", "inc.h", "hdr.hpp"]:
            self.assertTrue(isCPPLikeFile(name))
        self.assertFalse(isCPPLikeFile("readme.txt"))

    def test_is_proto_like(self):
        self.assertTrue(isProtoLikeFile("service.proto"))
        self.assertFalse(isProtoLikeFile("service.cc"))

    def test_copy_files(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            with open(os.path.join(src, "a.txt"), "w") as f:
                f.write("hello")
            os.mkdir(os.path.join(src, "sub"))
            with open(os.path.join(src, "sub", "b.txt"), "w") as f:
                f.write("world")
            _copyFilesBackNForth(src, dst)
            self.assertTrue(os.path.exists(os.path.join(dst, "a.txt")))
            self.assertTrue(os.path.exists(os.path.join(dst, "sub", "b.txt")))


class TestNinjaParserHelpers(unittest.TestCase):
    def test_short_name_and_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            parser = NinjaParser(td)
            parser.setContext("ctx")
            parser.vars["ctx"]["cmake_ninja_workdir"] = os.path.join(td, "build")
            parser.setDirectoryPrefix("prefix/")

            direct = parser.getShortName(os.path.join(td, "src/file.cc"))
            self.assertEqual(direct, ("/src/file.cc", "."))
            relative = parser.getShortName("gen.hh")
            self.assertEqual(relative, ("gen.hh", "prefix"))

            target = BuildTarget("out", ("out", None))
            alias = BuildTarget("alias", ("alias", None))
            target.setAlias(alias)
            build = Build([alias], Rule("phony"), [target], [])
            parser.buildEdges.append(build)
            parser.resolveAliases()
            self.assertIn(alias, build.getInputs())

    def test_cc_import_lookup_and_toplevels(self) -> None:
        parser = NinjaParser("/code")
        parser.setContext("ctx")
        imp = BazelCCImport("math")
        imp.staticLibrary = ["libm.a"]
        imp_target = BuildTarget("cc_import_math", ("math", None)).setOpaque(imp)
        parser.cc_imports = [imp_target]

        match = BuildTarget("libm.a", ("libm.a", None))
        self.assertEqual(parser.getCCImportForExternalDep(match), imp_target)

        real = BuildTarget("real", ("real", None))
        Build([real], Rule("cc"), [], [])
        phony = BuildTarget("all", ("all", None))
        Build([phony], Rule("phony"), [real], [])
        parser.all_outputs["all"] = phony
        parser.all_outputs["real"] = real
        tops = getToplevels(parser, ["all"])
        self.assertEqual(tops, [real])

    def test_parser_handles_includes_and_continuations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src.cc"
            src.write_text("int main() {return 0;}")
            other = Path(td) / "other.ninja"
            other.write_text("build helper: phony\n")

            main = Path(td) / "build.ninja"
            main.write_text(
                "rule cc\n"
                "  command = clang -c $in -o $out\n"
                "\n"
                "build out.o: cc src.cc\n"
                "  FLAGS = -DFOO $\n"
                "    -DBAR\n"
                "\n"
                "include other.ninja\n"
            )

            parser = NinjaParser(td)
            parser.setManuallyGeneratedTargets({})
            parser.setContext("ctx")
            parser.vars["ctx"]["cmake_ninja_workdir"] = td
            parser.setRemapPath({})
            parser.setCompilerIncludes([])
            parser.setCCImports([])
            parser.parse(main.read_text().splitlines(), td)
            parser.markDone()
            parser.endContext("ctx")

            self.assertIn("out.o", parser.all_outputs)
            self.assertGreaterEqual(len(parser.buildEdges), 2)
            flags = parser.buildEdges[0].vars.get("FLAGS", "")
            self.assertIn("-DBAR", flags)

    def test_resolve_name_prefers_additional_vars(self) -> None:
        parser = NinjaParser("/root")
        parser.setContext("ctx")
        parser.vars["ctx"]["cmake_ninja_workdir"] = "/root"
        resolved = parser._resolveName("${FOO}", {"FOO": "override"})
        self.assertEqual(resolved, "override")

    def test_parser_splits_custom_command_outputs_by_generator_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            build_file = Path(td) / "build.ninja"
            build_file.write_text(
                "rule CUSTOM_COMMAND\n"
                "  command = $COMMAND\n"
                "\n"
                "build generated/a.txt generated/b.txt: CUSTOM_COMMAND\n"
                "  COMMAND = python3 gen.py --output generated/a.txt && "
                "python3 gen.py generated/a.txt --output generated/b.txt\n"
            )

            parser = NinjaParser(td)
            parser.setManuallyGeneratedTargets({})
            parser.setContext("ctx")
            parser.vars["ctx"]["cmake_ninja_workdir"] = f"{td}/"
            parser.setRemapPath({})
            parser.setCompilerIncludes([])
            parser.setCCImports([])
            parser.parse(build_file.read_text().splitlines(), td)
            parser.markDone()
            parser.endContext("ctx")

            producer_a = parser.all_outputs["generated/a.txt"].producedby
            producer_b = parser.all_outputs["generated/b.txt"].producedby

            self.assertIsNot(producer_a, producer_b)
            self.assertEqual(["generated/a.txt"], [output.name for output in producer_a.outputs])
            self.assertEqual(["generated/b.txt"], [output.name for output in producer_b.outputs])
            self.assertIn(parser.all_outputs["generated/a.txt"], producer_b.getInputs())

    def test_execute_generator_runs_only_target_generator_command_after_cd(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            work_dir = tmp_path / "build"
            source = tmp_path / "ProtocolVersions.cmake"
            source.write_text("version")
            script = tmp_path / "protocol_version.py"
            script.write_text(
                "import argparse\n"
                "from pathlib import Path\n"
                "parser = argparse.ArgumentParser()\n"
                "parser.add_argument('--source')\n"
                "parser.add_argument('--generator')\n"
                "parser.add_argument('--output')\n"
                "args = parser.parse_args()\n"
                "output = Path(args.output)\n"
                "output.parent.mkdir(parents=True, exist_ok=True)\n"
                "output.write_text(args.generator)\n"
            )
            template = tmp_path / "ProtocolVersion.h.template"
            template.write_text("template")

            parser = NinjaParser(str(tmp_path))
            rule = Rule("CUSTOM_COMMAND")
            output = BuildTarget(
                "flow/include/flow/ProtocolVersion.h",
                ("ProtocolVersion.h", None),
            )
            build = Build(
                [output],
                rule,
                [
                    BuildTarget(str(script), (script.name, None)),
                    BuildTarget(str(template), (template.name, None)),
                    BuildTarget(str(source), (source.name, None)),
                ],
                [],
            )
            build.vars["cmake_ninja_workdir"] = f"{work_dir}/"
            rule.vars["command"] = (
                f"cd {work_dir}/flow && "
                f"{sys.executable} {script} --source {source} --generator cpp "
                f"--output {work_dir}/flow/include/flow/ProtocolVersion.h && "
                f"{sys.executable} {script} --source {source} --generator java "
                f"--output {work_dir}/flow/include/flow/ProtocolVersion.java"
            )

            temp_dir = Path(parser.executeGenerator(build, output))

            self.assertEqual(
                "cpp",
                (temp_dir / "flow/include/flow/ProtocolVersion.h").read_text(),
            )
            self.assertFalse(
                (temp_dir / "flow/include/flow/ProtocolVersion.java").exists(),
            )

    def test_execute_generator_for_split_build_runs_only_its_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            work_dir = tmp_path / "build"
            script = tmp_path / "gen.py"
            script.write_text(
                "import argparse\n"
                "from pathlib import Path\n"
                "parser = argparse.ArgumentParser()\n"
                "parser.add_argument('--value')\n"
                "parser.add_argument('--output')\n"
                "args = parser.parse_args()\n"
                "output = Path(args.output)\n"
                "output.parent.mkdir(parents=True, exist_ok=True)\n"
                "output.write_text(args.value)\n"
            )

            parser = NinjaParser(str(tmp_path))
            rule = Rule("CUSTOM_COMMAND")
            out_a = BuildTarget("generated/a.txt", ("a.txt", None))
            out_b = BuildTarget("generated/b.txt", ("b.txt", None))
            build = Build([out_a, out_b], rule, [], [])
            build.vars["cmake_ninja_workdir"] = f"{work_dir}/"
            rule.vars["command"] = (
                f"{sys.executable} {script} --value a --output {work_dir}/generated/a.txt && "
                f"{sys.executable} {script} --value b --output {work_dir}/generated/b.txt"
            )
            split_builds = build.splitByGeneratorCommands()
            target_build = split_builds[1]

            temp_dir = Path(parser.executeGenerator(target_build, out_b))

            self.assertFalse((temp_dir / "generated/a.txt").exists())
            self.assertEqual("b", (temp_dir / "generated/b.txt").read_text())

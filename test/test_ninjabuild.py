import os
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

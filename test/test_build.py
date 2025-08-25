import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from build import Build, BuildTarget, Rule
from bazel import BazelTarget, BazelBuild
from build import BazelBuildVisitorContext
from bazel import BazelGenRuleTarget
from bazel import getObject, bazelcache


class TestBuildUtils(unittest.TestCase):
    def test_handle_cpp_compile_command_filters_flags_and_defines(self) -> None:
        bazelbuild = BazelBuild("src/")
        ctx = BazelBuildVisitorContext(
            parentIsPhony=False,
            rootdir="/",
            bazelbuild=bazelbuild,
            flagsToIgnore=[],
            prefix="src",
        )
        lib = BazelTarget("cc_library", "lib", "src")
        ctx.current = lib
        output = BuildTarget("foo.o", ("foo.o", None)).markAsFile()
        rule = Rule("CXX")
        build = Build([output], rule, [], [])
        build.vars["DEFINES"] = "-DKEEP -DNDEBUG"
        build.vars["FLAGS"] = "-arch x86 -Wall -DDEF2 -g -isysroot /sys -L /lib -O3 -funroll"
        self.assertTrue(build._handleCPPCompileCommand(ctx, output))
        self.assertEqual(lib.defines, {'"KEEP"', '"DEF2"'})
        self.assertEqual(lib.copts, {'"-Wall"', '"-funroll"'})

    def test_get_core_command_extracts_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            src = tmp_path / "input.cpp"
            src.write_text("int main(){}")
            inp = BuildTarget(str(src), (str(src.name), None)).markAsFile()
            out = BuildTarget("out.o", ("out.o", None))
            rule = Rule("CUSTOM_COMMAND")
            build = Build([out], rule, [inp], [])
            build.vars["cmake_ninja_workdir"] = str(tmp_path)
            rule.vars["command"] = f"cd {tmp_path}/build && gcc -c {src} -o out.o"
            cmd, run_dir = build.getCoreCommand()
            self.assertTrue(cmd.strip().startswith("gcc -c"))
            self.assertEqual(run_dir, "/build")

    def test_is_cpp_command(self) -> None:
        cases = [
            ("clang -c foo.c", True),
            ("gcc -c foo.c", True),
            ("clang++ -c foo.cc", True),
            ("g++ -c foo.cc", True),
            ("python script.py", False),
            ("ld foo.o", False),
        ]
        for cmd, expected in cases:
            with self.subTest(cmd=cmd):
                self.assertIs(Build.isCPPCommand(cmd), expected)

    def test_is_static_archive_command(self) -> None:
        cases = [
            ("/usr/bin/ar rcs libfoo.a foo.o", True),
            ("llvm-ar rcs libfoo.a foo.o", True),
            ("tar cf archive.tar foo.o", False),
            ("gcc -c foo.c", False),
        ]
        for cmd, expected in cases:
            with self.subTest(cmd=cmd):
                self.assertIs(Build.isStaticArchiveCommand(cmd), expected)


class TestBuildResolveName(unittest.TestCase):
    def setUp(self) -> None:
        out = BuildTarget("out", ("out", None))
        self.build = Build([out], Rule("dummy"), [], [])
        self.build.vars = {"SRC": "main.c", "OBJ": "main.o"}
        self.template = "gcc -c $SRC -o $OBJ"

    def test_resolve_name_without_exceptvars(self) -> None:
        resolved = self.build._resolveName(self.template)
        self.assertEqual(resolved, "gcc -c main.c -o main.o")

    def test_resolve_name_with_exceptvars(self) -> None:
        resolved = self.build._resolveName(self.template, ["OBJ"])
        self.assertEqual(resolved, "gcc -c main.c -o $OBJ")


class TestBuildFeatures(unittest.TestCase):
    def test_custom_command_multiple_inputs_outputs(self) -> None:
        # Define inputs
        in1 = BuildTarget("src/in1.txt", ("src/in1.txt", "src"))
        in2 = BuildTarget("src/in2.txt", ("src/in2.txt", "src"))

        # Define outputs including one requiring aliasing
        out_alias = BuildTarget("alias/out1.txt", ("out1.txt", "alias"))
        # Matching output to trigger alias generation
        out_alias_helper = BuildTarget(
            "alias/alias/out1.txt", ("alias/alias/out1.txt", "alias")
        )
        out2 = BuildTarget("alias/out2.txt", ("out2.txt", "alias"))

        build = Build(
            [out_alias, out_alias_helper, out2], Rule("CUSTOM_COMMAND"), [in1, in2], []
        )

        bazelbuild = BazelBuild("")
        ctx = BazelBuildVisitorContext(
            parentIsPhony=False,
            rootdir="/root",
            bazelbuild=bazelbuild,
            flagsToIgnore=[],
            current=BazelTarget("cc_binary", "dummy", "alias"),
            prefix="",
        )
        cmd = "tool src/in1.txt src/in2.txt alias/out2.txt alias/out1.txt"

        build._handleCustomCommandForBazelGen(ctx, out2, cmd)

        gen = build.associatedBazelTarget
        self.assertIsInstance(gen, BazelGenRuleTarget)
        self.assertIn("$(location //src:in1.txt)", gen.cmd)
        self.assertIn("$(location //src:in2.txt)", gen.cmd)
        self.assertIn("$(location :out2.txt)", gen.cmd)
        self.assertEqual(gen.aliases.get("out1.txt"), "alias/out1.txt")

    def setUp(self) -> None:
        bazelcache.clear()

    def _make_ctx(self):
        bb = BazelBuild(prefix="")
        ctx = BazelBuildVisitorContext(False, "", bb, [], prefix="")
        return bb, ctx

    def test_soname_triggers_shared_library(self) -> None:
        bb, ctx = self._make_ctx()
        parent = BazelTarget("cc_binary", "parent", "")
        ctx.current = parent

        out = BuildTarget("libfoo.so", ("libfoo.so", None))
        build = Build([out], Rule("link"), [], [])
        build.vars["SONAME"] = "libfoo.so"

        cmd = "clang++ foo.o -shared -o libfoo.so"
        build.handleRuleProducedForBazelGen(ctx, out, cmd)

        self.assertEqual(len(parent.deps), 1)
        dep = next(iter(parent.deps))
        self.assertEqual(dep.type, "cc_library")
        self.assertIn(dep, bb.bazelTargets)

        shared = getObject(
            BazelTarget, "cc_shared_library", "shared_libfoo", dep.location
        )
        self.assertEqual(shared.type, "cc_shared_library")
        self.assertIn(dep, shared.deps)
        self.assertNotIn(shared, parent.deps)

    def test_link_executable_without_compile_flag(self) -> None:
        bb, ctx = self._make_ctx()
        parent = BazelTarget("cc_library", "parent", "")
        ctx.current = parent

        out = BuildTarget("foo", ("foo", None))
        build = Build([out], Rule("link"), [], [])
        cmd = "clang++ foo.o -o foo"
        build.handleRuleProducedForBazelGen(ctx, out, cmd)

        dep = next(iter(parent.deps))
        self.assertEqual(dep.type, "cc_binary")
        self.assertIn(dep, bb.bazelTargets)

    def test_static_archive_command(self) -> None:
        bb, ctx = self._make_ctx()
        parent = BazelTarget("cc_binary", "parent", "")
        ctx.current = parent

        out = BuildTarget("libbar.a", ("libbar.a", None))
        build = Build([out], Rule("archive"), [], [])
        cmd = "llvm-ar cr libbar.a foo.o"
        build.handleRuleProducedForBazelGen(ctx, out, cmd)

        dep = next(iter(parent.deps))
        self.assertEqual(dep.type, "cc_library")
        self.assertEqual(dep.name, "libbar.a")
        self.assertIn(dep, bb.bazelTargets)


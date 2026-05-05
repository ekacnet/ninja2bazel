import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bazel import (
    BazelCCImport,
    BazelCCProtoLibrary,
    BazelGenRuleTarget,
    BazelGRPCCCProtoLibrary,
)
from bazel import BazelTarget, BazelBuild, getObject, bazelcache
from build import BazelBuildVisitorContext, Build, BuildTarget, Rule
from ninjabuild import canBePruned


class TestBuildTargetBasics(unittest.TestCase):
    def test_basic_attributes(self):
        bt = BuildTarget("foo", ("foo", None))
        self.assertEqual(bt.name, "foo")
        self.assertEqual(bt.shortName, "foo")
        self.assertFalse(bt.implicit)

    def test_mark_as_file_and_top_level(self):
        bt = BuildTarget("foo", ("foo", None))
        bt.markAsFile()
        bt.markTopLevel()
        self.assertTrue(bt.is_a_file)
        self.assertTrue(bt.topLevel)

    def test_is_only_used_by(self):
        bt = BuildTarget("foo", ("foo", None))
        out1 = BuildTarget("out1", ("out1", None))
        Build([out1], Rule("phony"), [bt], [])
        self.assertTrue(bt.isOnlyUsedBy(["out1"]))


class TestBuildTargetUsage(unittest.TestCase):
    def test_no_users(self):
        dep = BuildTarget("dep", ("dep", None))
        self.assertFalse(dep.isUsedBy(["out"]))
        self.assertFalse(dep.isOnlyUsedBy(["out"]))

    def test_multiple_users_and_only_used_by(self):
        dep = BuildTarget("dep", ("dep", None))
        out1 = BuildTarget("out1", ("out1", None))
        Build([out1], Rule("cc"), [dep], [])
        self.assertTrue(dep.isUsedBy(["out1"]))
        self.assertTrue(dep.isOnlyUsedBy(["out1"]))

        out2 = BuildTarget("out2", ("out2", None))
        Build([out2], Rule("cc"), [dep], [])
        self.assertTrue(dep.isUsedBy(["out1"]))
        self.assertFalse(dep.isOnlyUsedBy(["out1"]))

    def test_deps_are_virtual(self):
        virt = BuildTarget("virt", ("virt", None))
        Build([virt], Rule("phony"), [], [])
        out = BuildTarget("out", ("out", None))
        Build([out], Rule("cc"), [], [virt])
        self.assertTrue(out.depsAreVirtual())

        real = BuildTarget("real", ("real", None))
        Build([real], Rule("cc"), [], [])
        out2 = BuildTarget("out2", ("out2", None))
        Build([out2], Rule("cc"), [], [real])
        self.assertFalse(out2.depsAreVirtual())

    def test_virtuality_for_external_and_files(self):
        dep = BuildTarget("vdep", ("vdep", None))
        self.assertTrue(dep.depsAreVirtual())
        dep.markAsExternal()
        self.assertFalse(dep.depsAreVirtual())
        dep.markAsFile()
        self.assertFalse(dep.depsAreVirtual())


class TestBuildTargetVirtualDeps(unittest.TestCase):
    def test_deps_are_virtual_for_empty_phony_chain(self) -> None:
        leaf = BuildTarget("leaf", ("leaf", None))
        Build([leaf], Rule("phony"), [], [])

        top = BuildTarget("top", ("top", None))
        Build([top], Rule("phony"), [], [leaf])

        self.assertTrue(top.depsAreVirtual())
        self.assertTrue(canBePruned(top.producedby))  # type: ignore

    def test_deps_are_not_virtual_when_external(self) -> None:
        ext = BuildTarget("ext", ("ext", None)).markAsExternal()
        self.assertFalse(ext.depsAreVirtual())


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

    def test_generated_source_cc_import_deps_are_propagated_to_current_target(self) -> None:
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

        imp = BazelCCImport("boost_filesystem")
        dep = BuildTarget("boost_filesystem", ("boost_filesystem", None)).setOpaque(imp)
        generated = BuildTarget("generated.cc", ("generated.cc", None))
        generated.setDeps([dep])

        Build._propagateGeneratedSourceCCImportDeps(generated, ctx)

        self.assertIn(imp, lib.deps)
        self.assertIn(imp, bazelbuild.bazelTargets)

    def test_cpp_compile_propagates_cc_import_deps_from_object_target(self) -> None:
        bazelbuild = BazelBuild("src/")
        ctx = BazelBuildVisitorContext(
            parentIsPhony=False,
            rootdir="/",
            bazelbuild=bazelbuild,
            flagsToIgnore=[],
            prefix="src",
        )
        lib = BazelTarget("cc_library", "flow", "src")
        ctx.current = lib

        imp = BazelCCImport("boost_filesystem")
        dep = BuildTarget("boost_filesystem", ("boost_filesystem", None)).setOpaque(imp)
        obj = BuildTarget("flow/CMakeFiles/flow.dir/Platform.actor.g.cpp.o", ("obj.o", None))
        obj.setDeps([dep])
        src = BuildTarget("flow/Platform.actor.g.cpp", ("flow/Platform.actor.g.cpp", None)).markAsFile()
        build = Build([obj], Rule("CXX_COMPILER"), [src], [])
        build.vars["FLAGS"] = ""
        build.vars["DEFINES"] = ""

        self.assertTrue(build._handleCPPCompileCommand(ctx, obj))

        self.assertIn(imp, lib.deps)
        self.assertIn(imp, bazelbuild.bazelTargets)

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

    def test_get_generator_commands_extracts_all_commands_with_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            work_dir = tmp_path / "build"
            script = tmp_path / "protocol_version.py"
            source = tmp_path / "ProtocolVersions.cmake"
            template = tmp_path / "ProtocolVersion.h.template"
            out = BuildTarget("flow/include/flow/ProtocolVersion.h", ("ProtocolVersion.h", None))
            rule = Rule("CUSTOM_COMMAND")
            build = Build(
                [out],
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
                f"python3 {script} --source {source} --generator cpp "
                f"--output {work_dir}/flow/include/flow/ProtocolVersion.h && "
                f"python3 {script} --source {source} --generator java "
                f"--output {work_dir}/flow/include/flow/ProtocolVersion.java && "
                f"python3 {script} --source {source} --generator python "
                f"--output {work_dir}/flow/include/flow/protocol_version.py"
            )

            commands = build.getGeneratorCommands()

            self.assertEqual(3, len(commands))
            self.assertEqual(["flow", "flow", "flow"], [run_dir for _, run_dir in commands])
            self.assertTrue(all(str(script) in cmd for cmd, _ in commands))

    def test_get_generator_commands_excludes_copy_and_cmake_commands(self) -> None:
        cases = [
            "cp input.txt generated.txt",
            "/bin/cp input.txt generated.txt",
            "/usr/bin/cmake -E copy input.txt generated.txt",
            "/opt/bin/cmake -E copy input.txt generated.txt",
        ]
        for command in cases:
            with self.subTest(command=command):
                inp = BuildTarget("input.txt", ("input.txt", None)).markAsFile()
                out = BuildTarget("generated.txt", ("generated.txt", None))
                rule = Rule("CUSTOM_COMMAND")
                build = Build([out], rule, [inp], [])
                rule.vars["command"] = command

                self.assertEqual([], build.getGeneratorCommands())

    def test_get_generator_commands_does_not_reuse_setup_for_excluded_command(self) -> None:
        inp = BuildTarget("input.txt", ("input.txt", None)).markAsFile()
        out = BuildTarget("generated.txt", ("generated.txt", None))
        rule = Rule("CUSTOM_COMMAND")
        build = Build([out], rule, [inp], [])
        rule.vars["command"] = (
            "mkdir copied && cp input.txt copied/generated.txt && "
            "python3 gen.py input.txt generated.txt"
        )

        self.assertEqual(
            [("python3 gen.py input.txt generated.txt", None)],
            build.getGeneratorCommands(),
        )

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

    def test_generated_assembly_output_is_added_as_source(self) -> None:
        out = BuildTarget("bindings/c/fdb_c.g.S", ("bindings/c/fdb_c.g.S", None))
        build = Build([out], Rule("CUSTOM_COMMAND"), [], [])
        gen = BazelGenRuleTarget("generate_fdb_c_asm", ".")
        gen.addOut("bindings/c/fdb_c.g.S")
        build.associatedBazelTarget = gen

        lib = BazelTarget("cc_library", "fdb_c", ".")
        bazelbuild = BazelBuild("")
        ctx = BazelBuildVisitorContext(
            parentIsPhony=False,
            rootdir="/root",
            bazelbuild=bazelbuild,
            flagsToIgnore=[],
            current=lib,
            prefix="",
        )

        build._handleCustomCommandForBazelGen(ctx, out, "tool bindings/c/fdb_c.g.S")

        generated_src = next(iter(gen.outs))
        self.assertIn(generated_src, lib.srcs)
        self.assertNotIn(generated_src, lib.data)

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


class TestBuildProtoAndLinkHandling(unittest.TestCase):
    def setUp(self) -> None:
        bazelcache.clear()

    def _ctx(self) -> BazelBuildVisitorContext:
        bb = BazelBuild("")
        ctx = BazelBuildVisitorContext(False, "/src", bb, [], prefix="")
        ctx.current = BazelTarget("cc_library", "parent", "")
        return ctx

    def test_handle_protobuf_header_keeps_context(self) -> None:
        ctx = self._ctx()
        out = BuildTarget("foo.pb.h", ("foo.pb.h", "proto"))
        build = Build([out], Rule("CUSTOM_COMMAND"), [], [])
        build.vars["COMMAND"] = "/usr/bin/bin/protoc something"
        kept = ctx.current
        self.assertTrue(build.handleRuleProducedForBazelGen(ctx, out, "cmd"))
        self.assertIs(ctx.current, kept)
        self.assertIs(ctx.next_current, kept)
        self.assertGreater(len(kept.deps), 0)  # type: ignore

    def test_handle_grpc_protobuf_header_keeps_current_grpc_context(self) -> None:
        ctx = self._ctx()
        current = BazelGRPCCCProtoLibrary("foo_cc_grpc", "proto")
        ctx.current = current
        out = BuildTarget("foo.grpc.pb.h", ("foo.grpc.pb.h", "proto"))
        build = Build([out], Rule("CUSTOM_COMMAND"), [], [])
        build.vars["COMMAND"] = "/usr/bin/bin/protoc something"

        self.assertTrue(build.handleRuleProducedForBazelGen(ctx, out, "cmd"))

        self.assertIs(ctx.current, current)
        self.assertIs(ctx.next_current, current)
        self.assertNotIn(current, current.deps)

    def test_handle_protobuf_header_keeps_current_cc_proto_context(self) -> None:
        ctx = self._ctx()
        current = BazelCCProtoLibrary("foo_cc_proto", "proto")
        ctx.current = current
        out = BuildTarget("foo.pb.h", ("foo.pb.h", "proto"))
        build = Build([out], Rule("CUSTOM_COMMAND"), [], [])
        build.vars["COMMAND"] = "/usr/bin/bin/protoc something"

        self.assertTrue(build.handleRuleProducedForBazelGen(ctx, out, "cmd"))

        self.assertIs(ctx.current, current)
        self.assertIs(ctx.next_current, current)
        self.assertNotIn(current, current.deps)

    def test_revisit_shared_library_reuses_existing_target(self) -> None:
        ctx = self._ctx()
        out = BuildTarget("libfoo.so", ("libfoo.so", None))
        build = Build([out], Rule("link"), [], [])
        build.associatedBazelTarget = BazelTarget("cc_shared_library", "libfoo", "")
        build.associatedBazelTarget.addDep(BazelTarget("cc_library", "libfoo", ""))

        should_skip = build._handleCPPLinkCommand(out, "clang++ libfoo.so", ctx)
        self.assertFalse(should_skip)
        self.assertIsInstance(ctx.current, BazelTarget)

    def test_include_handling_pregenerated(self) -> None:
        ctx = BazelBuildVisitorContext(False, "/root", BazelBuild(""), [], prefix="")
        ctx.current = BazelTarget("cc_library", "lib", "")
        el = BuildTarget("obj.o", ("obj.o", None))
        include_dir = "/work/pregenerated/inc"
        el.setIncludedFiles([("hdr.h", include_dir)])
        Build._handleIncludeBazelTarget(el, ctx, "/work/")
        self.assertIn(("pregenerated/inc", False), ctx.current.includeDirs)

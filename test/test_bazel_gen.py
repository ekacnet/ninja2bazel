import unittest

from bazel import (
    BazelBuild,
    BazelTarget,
    ExportedFile,
    BazelProtoLibrary,
    BazelCCProtoLibrary,
    BazelGRPCCCProtoLibrary,
    BazelGenRuleTarget,
)


class TestBazelGen(unittest.TestCase):
    def test_gen_additional_deps_splits_c_sources(self) -> None:
        build = BazelBuild("src/")
        target = BazelTarget("cc_library", "lib", "src")
        c_src = ExportedFile("a.c", "src")
        cpp_src = ExportedFile("b.cpp", "src")
        target.addSrc(c_src)
        target.addSrc(cpp_src)
        target.copts.add('"-std=c11"')
        target.copts.add('"-O2"')
        header = ExportedFile("lib.h", "src")
        target.addHdr(header)
        dep = BazelTarget("cc_library", "dep", "src")
        target.addDep(dep)
        build.bazelTargets.add(target)

        build.genAdditionalDeps()

        sublibs = [
            t for t in build.bazelTargets if isinstance(t, BazelTarget) and t.name == "_lib_c"
        ]
        self.assertEqual(len(sublibs), 1)
        sublib = sublibs[0]
        self.assertIn(c_src, sublib.srcs)
        self.assertNotIn(cpp_src, sublib.srcs)
        self.assertIn(header, sublib.hdrs)
        self.assertIn(dep, sublib.deps)
        self.assertIn(sublib, target.deps)
        self.assertNotIn(c_src, target.srcs)
        self.assertIn(cpp_src, target.srcs)
        self.assertIn('"-std=c11"', sublib.copts)
        self.assertNotIn('"-std=c11"', target.copts)

    def test_gen_bazel_build_content_includes_various_targets(self) -> None:
        build = BazelBuild("src/")

        proto = BazelProtoLibrary("foo_proto", "src")
        proto.addSrc(ExportedFile("foo.proto", "src"))
        proto.need_helpers_bzl = lambda: False  # type: ignore[attr-defined]

        cc_proto = BazelCCProtoLibrary("foo_proto_cc", "src")
        cc_proto.addDep(proto)
        cc_proto.need_helpers_bzl = lambda: False  # type: ignore[attr-defined]

        grpc = BazelGRPCCCProtoLibrary("foo_proto_cc_grpc", "src")
        grpc.addDep(cc_proto)
        grpc.addSrc(proto)
        grpc.need_helpers_bzl = lambda: False  # type: ignore[attr-defined]

        gen = BazelGenRuleTarget("gen_hdr", "src")
        gen.cmd = "touch $@"
        gen.addOut("generated.h")
        gen_out = next(iter(gen.outs))
        gen.need_helpers_bzl = lambda: False  # type: ignore[attr-defined]

        lib = BazelTarget("cc_library", "mylib", "src")
        lib.addSrc(ExportedFile("lib.cc", "src"))
        lib.addHdr(gen_out, ("include", True))
        lib.addIncludeDir(("include", True))
        lib.addDep(grpc)

        build.bazelTargets.update({proto, cc_proto, grpc, gen, lib})

        content = build.genBazelBuildContent()
        src_content = content["src"]

        self.assertIn("proto_library(", src_content)
        self.assertIn("cc_grpc_library(", src_content)
        self.assertIn("genrule(", src_content)
        self.assertIn("cc_library(", src_content)
        self.assertIn("foo_proto_cc_grpc", src_content)
        self.assertIn("generated.h", src_content)
        self.assertIn(
            'load("@rules_proto//proto:defs.bzl", "proto_library")', src_content
        )
        self.assertIn(
            'load("@com_github_grpc_grpc//bazel:cc_grpc_library.bzl", "cc_grpc_library")',
            src_content,
        )
        self.assertIn(
            'load("//src:helpers.bzl", "add_bazel_out_prefix")', src_content
        )


import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bazel import (
    BazelBuild,
    BazelCCImport,
    BazelCCProtoLibrary,
    BazelGRPCCCProtoLibrary,
    BazelGenRuleTarget,
    BazelProtoLibrary,
    BazelTarget,
    ExportedFile,
    _getPrefix,
    compare_deps,
    compare_imports,
    findCommonPaths,
    globifyPath,
)


class DummyTarget(BazelTarget):
    pass


class TestBazelTarget(unittest.TestCase):
    def test_as_bazel_binary(self):
        b = BazelTarget("cc_binary", "app", "src")
        b.addSrc(ExportedFile("main.cpp", "src"))
        res = b.asBazel({})
        expected = {
            "app": [
                "cc_binary(",
                '    name = "app",',
                "    srcs = [",
                '        ":main.cpp",',
                "    ],",
                "    linkopts = [",
                "    ],",
                '    visibility = ["//visibility:public"],',
                ")",
            ]
        }
        self.assertEqual(res, expected)


class TestBazelUtils(unittest.TestCase):
    def test_get_prefix(self):
        t1 = BazelTarget("cc_library", "foo", "src")
        self.assertEqual(_getPrefix(t1, "src", defaultPrefix="foo"), "")
        t2 = BazelTarget("cc_library", "bar", "lib")
        self.assertEqual(_getPrefix(t2, "src", defaultPrefix="foo"), "//lib")
        t3 = BazelTarget("cc_library", "ext", "@ext//")
        self.assertEqual(_getPrefix(t3, "src", defaultPrefix="foo"), "@ext//")

    def test_compare_deps(self):
        a = BazelTarget("cc_library", "a", "src")
        b = BazelTarget("cc_library", "b", "src")
        cmp = compare_deps(a, b, lambda x: _getPrefix(x, "src", defaultPrefix="foo"))
        self.assertLess(cmp, 0)
        self.assertGreater(
            compare_deps(b, a, lambda x: _getPrefix(x, "src", defaultPrefix="foo")), 0
        )

    def test_compare_imports(self):
        self.assertEqual(compare_imports('load("@a//:foo")', 'load("@a//:foo")'), 0)
        self.assertLess(compare_imports('load("@a//:foo")', 'load("@b//:bar")'), 0)
        self.assertGreater(compare_imports('load("@b//:bar")', 'load("@a//:foo")'), 1 - 1)

    def test_find_common_paths(self):
        paths = [
            "/a/b/c.h",
            "/a/b/d.h",
        ]
        self.assertEqual(findCommonPaths(paths), ["/a/b"])
        paths = ["/a/x/c.h", "/a/y/d.h"]
        res = findCommonPaths(paths)
        self.assertEqual(set(res), {"/a/x", "/a/y"})

    def test_globify_path(self):
        self.assertEqual(globifyPath("src", "h"), "src/**/*.h")

    def test_cc_import_as_bazel(self):
        imp = BazelCCImport("foo")
        imp.setHdrs(["/foo.h"])
        imp.setLocation("src")
        res = imp.asBazel({})
        self.assertIn("foo", res)
        self.assertIn("raw_foo", res)
        self.assertTrue(any("cc_import(" in line for line in res["raw_foo"]))


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
            t
            for t in build.bazelTargets
            if isinstance(t, BazelTarget) and t.name == "_lib_c"
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
        self.assertNotIn(
            'load("//src:helpers.bzl", "add_bazel_out_prefix")', src_content
        )

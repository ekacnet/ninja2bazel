import os
from bazel import BazelBuild, BazelTarget, ExportedFile, BazelProtoLibrary, BazelCCProtoLibrary, BazelGRPCCCProtoLibrary, BazelGenRuleTarget


def test_gen_additional_deps_splits_c_sources():
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

    sublibs = [t for t in build.bazelTargets if isinstance(t, BazelTarget) and t.name == "_lib_c"]
    assert len(sublibs) == 1
    sublib = sublibs[0]
    assert c_src in sublib.srcs
    assert cpp_src not in sublib.srcs
    assert header in sublib.hdrs
    assert dep in sublib.deps
    assert sublib in target.deps
    assert c_src not in target.srcs
    assert cpp_src in target.srcs
    assert '"-std=c11"' in sublib.copts
    assert '"-std=c11"' not in target.copts


def test_gen_bazel_build_content_includes_various_targets(tmp_path):
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

    assert "proto_library(" in src_content
    assert "cc_grpc_library(" in src_content
    assert "genrule(" in src_content
    assert "cc_library(" in src_content
    assert "foo_proto_cc_grpc" in src_content
    assert "generated.h" in src_content
    assert 'load("@rules_proto//proto:defs.bzl", "proto_library")' in src_content
    assert 'load("@com_github_grpc_grpc//bazel:cc_grpc_library.bzl", "cc_grpc_library")' in src_content
    assert 'load("//src:helpers.bzl", "add_bazel_out_prefix")' in src_content

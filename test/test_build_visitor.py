import unittest

from bazel import BazelBuild, BazelTarget, bazelcache
from build import BazelBuildVisitorContext, Build, BuildTarget, Rule
from build_visitor import BuildVisitor


class TestBuildVisitorPaths(unittest.TestCase):
    def setUp(self) -> None:
        bazelcache.clear()

    def test_visitor_handles_alias(self) -> None:
        bb = BazelBuild("")
        ctx = BazelBuildVisitorContext(False, "/root", bb, [], prefix="")
        ctx.current = BazelTarget("cc_library", "lib", "")

        alias = BuildTarget("alias.o", ("alias.o", None))
        real = BuildTarget("real.o", ("real.o", None)).markAsFile()
        alias.setAlias(real)
        rule = Rule("CXX")
        rule.vars["command"] = "clang -c $in -o $out"
        build = Build([alias], rule, [real], [])
        build.vars["FLAGS"] = "-Wall"
        ctx.producer = build
        visitor = BuildVisitor.getVisitor()

        alias.visitGraph(visitor, ctx)
        self.assertTrue(ctx.current.srcs)

    def test_visit_produced_missing_command(self) -> None:
        bb = BazelBuild("")
        ctx = BazelBuildVisitorContext(False, "/root", bb, [], prefix="")
        ctx.current = BazelTarget("cc_library", "lib", "")
        out = BuildTarget("out.o", ("out.o", None))
        build = Build([out], Rule("CXX"), [], [])
        self.assertFalse(BuildVisitor.visitProduced(ctx, out, build))

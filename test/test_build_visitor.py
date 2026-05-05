import unittest

from bazel import BazelBuild, BazelGenRuleTarget, BazelTarget, bazelcache
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

    def test_visit_custom_command_uses_target_specific_generator_command(self) -> None:
        bb = BazelBuild("")
        ctx = BazelBuildVisitorContext(False, "/root", bb, [], prefix="")
        ctx.current = BazelTarget("cc_library", "lib", "")
        source = BuildTarget("flow/ProtocolVersions.cmake", ("ProtocolVersions.cmake", None)).markAsFile()
        template = BuildTarget(
            "flow/protocolversion/ProtocolVersion.h.template",
            ("ProtocolVersion.h.template", None),
        ).markAsFile()
        out_a = BuildTarget("generated/a.txt", ("a.txt", None))
        out_b = BuildTarget("generated/b.txt", ("b.txt", None))
        rule = Rule("CUSTOM_COMMAND")
        build = Build([out_a, out_b], rule, [source, template], [])
        rule.vars["command"] = (
            "tool flow/ProtocolVersions.cmake --output generated/a.txt && "
            "tool flow/ProtocolVersions.cmake --output generated/b.txt"
        )
        split_builds = build.splitByGeneratorCommands()
        target_build = split_builds[1]

        self.assertTrue(BuildVisitor.visitProduced(ctx, out_b, target_build))

        gen = target_build.associatedBazelTarget
        self.assertIsInstance(gen, BazelGenRuleTarget)
        self.assertEqual({"b.txt"}, {out.name for out in gen.outs})
        self.assertIn("b.txt", gen.cmd)
        self.assertNotIn("generated/a.txt", gen.cmd)

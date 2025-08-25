from bazel import BazelTarget, BazelBuild
from build import Build, BuildTarget, Rule, BazelBuildVisitorContext


def test_handle_cpp_compile_command_filters_flags_and_defines():
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
    build.vars["FLAGS"] = (
        "-arch x86 -Wall -DDEF2 -g -isysroot /sys -L /lib -O3 -funroll"
    )
    assert build._handleCPPCompileCommand(ctx, output)
    assert lib.defines == {'"KEEP"', '"DEF2"'}
    assert lib.copts == {'"-Wall"', '"-funroll"'}


def test_get_core_command_extracts_run_directory(tmp_path):
    src = tmp_path / "input.cpp"
    src.write_text("int main(){}")
    inp = BuildTarget(str(src), (str(src.name), None)).markAsFile()
    out = BuildTarget("out.o", ("out.o", None))
    rule = Rule("CUSTOM_COMMAND")
    build = Build([out], rule, [inp], [])
    build.vars["cmake_ninja_workdir"] = str(tmp_path)
    rule.vars["command"] = f"cd {tmp_path}/build && gcc -c {src} -o out.o"
    cmd, run_dir = build.getCoreCommand()
    assert cmd.strip().startswith("gcc -c")
    assert run_dir == "/build"

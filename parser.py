#!/usr/bin/env python3
import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from typing import Dict, List, Optional, Set

from build import CONFIGURE_FILE_TOOL_PATH
from cc_import_parse import parseCCImports
from configure_file import parse_configure_files_list, parse_configure_vars
from ninjabuild import genBazelBuildFiles, getBuildTargets


def parse_manually_generated(manually_generated: List[str]) -> Dict[str, str]:
    ret = {}
    if not manually_generated:
        return ret
    for e in manually_generated:
        if "=" not in e:
            logging.fatal(
                f"Manually generated dependency {e} is not in the form key=value"
            )
            sys.exit(-1)
        v = e.split("=")
        ret[v[0]] = v[1]

    return ret


# FIXME: This should be a parameter
# if relative it's relative to the rootdir
BUILD_CUSTOMIZATION_DIRECTORY = "bazel/cpp"
TOOL_SOURCE_DIRECTORY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "tools",
)


def _build_post_treatment_command(script: str, build_file: str) -> List[str]:
    if script.endswith(".py"):
        return [sys.executable, script, build_file]
    return [script, build_file]


def _top_level_build_dir(rootdir: str, prefix: str) -> str:
    if prefix in ("", "."):
        return rootdir
    return os.path.join(rootdir, prefix)


def _configure_vars_from_cli_paths(
    rootdir: str,
    binary_dir: str,
    prefix: str,
    configure_vars: Optional[List[str]],
) -> Dict[str, str]:
    ret = {
        "CMAKE_SOURCE_DIR": os.path.abspath(_top_level_build_dir(rootdir, prefix)),
        "CMAKE_BINARY_DIR": os.path.abspath(binary_dir),
    }
    ret.update(parse_configure_vars(configure_vars))
    return ret


def _copy_if_different(source: str, destination: str) -> None:
    source_abs = os.path.abspath(source)
    destination_abs = os.path.abspath(destination)
    if source_abs == destination_abs:
        return
    shutil.copy2(source_abs, destination_abs)


def install_configure_file_tool(rootdir: str, prefix: str) -> None:
    tool_destination = os.path.join(
        _top_level_build_dir(rootdir, prefix),
        CONFIGURE_FILE_TOOL_PATH,
    )
    os.makedirs(os.path.dirname(tool_destination), exist_ok=True)
    _copy_if_different(
        os.path.join(TOOL_SOURCE_DIRECTORY, "render_configure_file.py"),
        tool_destination,
    )


def run_post_treatments(
    build_file: str, post_treatments: Optional[List[str]]
) -> None:
    if not post_treatments:
        return

    for script in post_treatments:
        if not os.path.exists(script):
            logging.fatal(f"Post-treatment script {script} does not exist")
            sys.exit(-1)

        cmd = _build_post_treatment_command(script, build_file)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            continue

        logging.error(f"Post-treatment failed for {build_file} with script {script}")
        if result.stdout:
            logging.error(result.stdout.rstrip())
        if result.stderr:
            logging.error(result.stderr.rstrip())
        sys.exit(result.returncode or -1)


def _add_needed_configure_output(outputs: Set[str], path: Optional[str], binary_dir: str) -> None:
    if not path:
        return

    normalized = os.path.normpath(path).replace(os.path.sep, "/")
    outputs.add(normalized)
    if os.path.isabs(path):
        rel = os.path.relpath(path, binary_dir)
        normalized = os.path.normpath(rel).replace(os.path.sep, "/")
        outputs.add(normalized)

    if normalized.startswith("pregenerated/"):
        outputs.add(normalized[len("pregenerated/") :])
    else:
        outputs.add(f"pregenerated/{normalized}")


def collect_needed_configure_outputs(top_levels: List[object], binary_dir: str) -> Set[str]:
    outputs: Set[str] = set()
    seen: Set[str] = set()

    def visit(target: object) -> None:
        name = getattr(target, "name", None)
        if name in seen:
            return
        if name is not None:
            seen.add(name)
            _add_needed_configure_output(outputs, name, binary_dir)
        _add_needed_configure_output(outputs, getattr(target, "shortName", None), binary_dir)

        for include, include_dir in getattr(target, "includes", set()):
            _add_needed_configure_output(outputs, include, binary_dir)
            if include_dir is not None:
                _add_needed_configure_output(outputs, os.path.join(include_dir, include), binary_dir)

        build = getattr(target, "producedby", None)
        if build is None:
            return
        for dep in build.getInputs():
            visit(dep)
        for dep in build.depends:
            if dep.depsAreVirtual():
                continue
            visit(dep)

    for top_level in top_levels:
        visit(top_level)
    return outputs


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s - %(levelname)s - %(message)s - Line: %(lineno)d",
    )
    parser = argparse.ArgumentParser(description="Process Ninja build input file.")
    parser.add_argument("filename", type=str, help="Ninja build input file")
    parser.add_argument("rootdir", type=str, help="Root directory")
    parser.add_argument(
        "-m",
        "--manually_generated",
        action="append",
        help="Manually generated dependencies",
    )
    parser.add_argument(
        "--remap",
        action="append",
        help="Which path  are remopped to which path",
    )
    parser.add_argument(
        "-p",
        "--prefix",
        default="",
        help="Initial directory prefix for generated Bazel BUILD files",
    )
    parser.add_argument(
        "--imports",
        action="append",
        help="A file containing a list of cc_imports to be added to the BUILD files",
    )
    parser.add_argument(
        "--top-level-target",
        action="append",
        help="The name of top level target(s) to be generated, if not specified all targets will be generated",
    )
    parser.add_argument(
        "--post-treatment",
        action="append",
        help="Executable run after each generated BUILD.bazel file; receives the file path to rewrite",
    )
    parser.add_argument(
        "--configure_files_list",
        help="File containing CMake configure_file(...) lines used to generate pregenerated files",
    )
    parser.add_argument(
        "--configure_var",
        action="append",
        help="CMake configure_file variable in the form key=value",
    )

    args = parser.parse_args(argv)

    filename = args.filename
    rootdir = args.rootdir
    manually_generated = parse_manually_generated(args.manually_generated)

    if not filename or not rootdir:
        logging.fatal(
            "Ninja build input file and/or folder where the code is located is/are missing"
        )
        sys.exit(-1)
    with open(filename, "r") as f:
        raw_ninja = f.readlines()

    raw_imports = []
    location = ""
    if len(args.imports or []) > 0:
        for i in args.imports:
            if not os.path.exists(i):
                logging.fatal(f"Imports file {i} does not exist")
                sys.exit(-1)
            p = os.path.dirname(i)
            # Skip the trailing /
            loc = p.replace(rootdir, "")[1:]
            if location != "" and loc != location:
                raise Exception(
                    "Not all the cc_imports files are in the same place current: {location} new: {loc}"
                )
            location = loc

            with open(i, "r") as f:
                raw_imports.extend(f.readlines())

    start = time.time()
    cc_imports = parseCCImports(raw_imports, location)
    end = time.time()
    print(f"Time to parse cc_imports: {end - start}", file=sys.stdout)
    start = time.time()
    compilerIncludes = getCompilerIncludesDir()
    end = time.time()
    print(f"Time to getCompilerIncludes: {end - start}", file=sys.stdout)
    start = time.time()

    prefix = ""
    if args.prefix != "":
        if not os.path.exists(f"{rootdir}{os.path.sep}{args.prefix}"):
            logging.fatal(f"Prefix directory {args.prefix} does not exist in {rootdir}")
            sys.exit(-1)
        if not os.path.isdir(f"{rootdir}{os.path.sep}{args.prefix}"):
            logging.fatal(f"Prefix directory {args.prefix} is not a directory")
            sys.exit(-1)
        # Should we have a special case for "." ?
        prefix = f"{args.prefix}{os.path.sep}"

    cur_dir = os.path.dirname(os.path.abspath(filename))
    logging.info("Parsing ninja file and buildTargets")
    if not rootdir.endswith(os.path.sep):
        rootdir = f"{rootdir}{os.path.sep}"
    remap = {}
    if args.remap:
        for e in args.remap:
            (fromPath, toPath) = e.split("=")
            remap[fromPath] = toPath

    top_levels_targets = getBuildTargets(
        raw_ninja,
        cur_dir,
        filename,
        manually_generated,
        rootdir,
        prefix,
        remap,
        cc_imports,
        compilerIncludes,
        args.top_level_target or ["all"],
    )
    end = time.time()
    print(f"Time to getBuildTargets: {end - start}", file=sys.stdout)
    start = time.time()
    needed_configure_outputs = collect_needed_configure_outputs(top_levels_targets, cur_dir)
    configure_files = parse_configure_files_list(
        args.configure_files_list,
        rootdir,
        cur_dir,
        _configure_vars_from_cli_paths(
            rootdir,
            cur_dir,
            args.prefix,
            args.configure_var,
        ),
        needed_configure_outputs,
    )
    end = time.time()
    print(f"Time to parse configure_files: {end - start}", file=sys.stdout)
    start = time.time()
    if configure_files:
        install_configure_file_tool(rootdir, args.prefix)
    logging.info("Generating Bazel BUILD files from buildTargets")
    logging.info(f"There are {len(top_levels_targets)} top level targets")

    output = genBazelBuildFiles(
        top_levels_targets,
        rootdir,
        prefix,
        BUILD_CUSTOMIZATION_DIRECTORY,
        configure_files,
        cur_dir,
    )
    end = time.time()
    print(f"Time to generate Bazel's BUILD files: {end - start}", file=sys.stdout)
    logging.info("Done")
    for name, content in output.items():
        if len(content) > 1:
            logging.info(
                f"Wrote {rootdir}{name}{os.path.sep}BUILD.bazel len = {len(content)}"
            )
            build_file = f"{rootdir}{name}{os.path.sep}BUILD.bazel"
            with open(build_file, "w") as f:
                f.write(content)
            run_post_treatments(build_file, args.post_treatment)


def getCompilerIncludesDir(compiler: str = "clang++") -> List[str]:
    sed_cmd = "/^[[:space:]]\\{1,\\}/p"
    cmd = f"""echo "" |{compiler} -Wp,-v -x c++ - -fsyntax-only  2>&1 |sed -n -e '{sed_cmd}'  | sed 's/^[ \\t]*//'"""
    ret: List[str] = []
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    ret.extend(result.stdout.split("\n"))
    return ret


if __name__ == "__main__":
    main()

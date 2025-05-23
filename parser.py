#!/usr/bin/env python3
import argparse
import logging
import os
import subprocess
import sys
from typing import Dict, List
import time

from cc_import_parse import parseCCImports
from ninjabuild import genBazelBuildFiles, getBuildTargets


def parse_manually_generated(manually_generated: List[str]) -> Dict[str, str]:
    ret = {}
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

def main():

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
    args = parser.parse_args()

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
    if len(args.imports) > 0:
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
        prefix = f"{args.prefix}{os.path.sep}"

    cur_dir = os.path.dirname(os.path.abspath(filename))
    logging.info("Parising ninja file and buildTargets")
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
    )
    end = time.time()
    print(f"Time to getBuildTargets: {end - start}", file=sys.stdout)
    start = time.time()
    logging.info("Generating Bazel BUILD files from buildTargets")
    logging.info(f"There is {len(top_levels_targets)} top level targets")

    output = genBazelBuildFiles(top_levels_targets, rootdir, prefix, BUILD_CUSTOMIZATION_DIRECTORY)
    end = time.time()
    print(f"Time to generate Bazel's BUILD files: {end - start}", file=sys.stdout)
    logging.info("Done")
    for name, content in output.items():
        logging.info(f"Wrote {rootdir}{name}{os.path.sep}BUILD.bazel")
        with open(f"{rootdir}{name}{os.path.sep}BUILD.bazel", "w") as f:
            f.write(content)


def getCompilerIncludesDir(compiler: str = "clang++-18") -> List[str]:
    cmd = f"""echo "" |{compiler} -Wp,-v -x c++ - -fsyntax-only  2>&1 |sed -n -e '/^\\s\\+/p'  | sed 's/^[ \\t]*//'"""
    ret: List[str] = []
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    ret.extend(result.stdout.split("\n"))

    return ret


if __name__ == "__main__":
    main()

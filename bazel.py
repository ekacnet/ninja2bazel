import logging
import os
import re
from functools import cache, cmp_to_key, total_ordering
from typing import (Any, Callable, Dict, Generator, List, Optional, Set, Type,
                    TypeVar, Union)

BazelTargetStrings = Dict[str, List[str]]
# Define a type variable that can be any type
T = TypeVar("T")

CompilationFlags = Dict[str, Union[str, Set[str]]]


def _getPrefix(d: Union["BaseBazelTarget", "BazelCCImport"], location: str) -> str:
    if d.location.startswith("@"):
        return d.location
    elif d.location.startswith("//"):
        return d.location
    return f"//{d.location}" if d.location != location else ""


def compare_deps(
    obja: Union["BazelCCImport", "BaseBazelTarget"],
    objb: Union["BazelCCImport", "BaseBazelTarget"],
    _getPrefix=Callable[[Union["BazelCCImport", "BaseBazelTarget"]], str],
) -> int:
    a = f"{_getPrefix(obja)}{obja.targetName()}"
    b = f"{_getPrefix(objb)}{objb.targetName()}"
    ret = 0
    if a[0] == b[0]:
        if a == b:
            ret = 0
        elif a > b:
            ret = 1
        else:
            ret = -1
    elif a[0] == ":":
        ret = -1
    elif b[0] == ":":
        # a > b
        ret = 1
    elif b[0] == "@":
        # a > b
        ret = 1
    elif a[0] == "@":
        ret = -1
    return ret


def compare_imports(a, b):
    # get rid of load("
    a = a[6:].replace(':', '\x00').replace('/', '\x01')
    b = b[6:].replace(':', '\x00').replace('/', '\x01')
    ret = 0
    if a[0] == b[0]:
        if a == b:
            ret = 0
        elif a > b:
            ret = 1
        else:
            ret = -1
    elif b[0] == "@":
        # a > b
        ret = 1
    elif a[0] == "@":
        # a < b
        ret = -1
    else:
        assert False
        ret = 1
    return ret


IncludeDir = tuple[str, bool]


def findCommonPaths(paths: List[str]) -> List[str]:
    split_paths = [p.split(os.path.sep)[:-1] for p in paths]

    joined = zip(*split_paths)
    # now joined a is a list of list, each element of the first list is a list of the directory for that level
    # if at a given level all the paths are the same then we can add it to the common path
    new_joined: List[List[str]] = []
    for e in joined:
        # dedup the entries
        new_joined.append(list(set(e)))

    ret = []
    common = []
    for e2 in new_joined:
        if len(e2) == 1:
            common.append(e2[0])
        else:
            for el in e2:
                ret.append("/".join([*common, el]))
            break

    if len(ret) == 0:
        ret.append("/".join(common))

    return ret


def globifyPath(path: str, ext: str) -> str:
    return f"{path}/**/*.{ext}"


class BazelCCImport:
    def __init__(self, name: str):
        self.name = name
        self.system_provided = 0
        self.hdrs: list[str] = []
        self._deps: set[Union["BazelCCImport", "BaseBazelTarget"]] = set()
        self.staticLibrary: Optional[str] = None
        self.sharedLibrary: Optional[str] = None
        self.location = ""
        self.skipWrapping = False
        self.includes: Optional[List[str]] = None
        self.alias: Optional[str] = None
    
    def setAlias(self, alias: str):
        self.alias = alias

    @property
    def deps(self) -> set[Union["BazelCCImport", "BaseBazelTarget"]]:
        return self._deps

    @deps.setter
    def deps(
        self, deps: Union[List[Union["BaseBazelTarget", "BazelCCImport"]], List[str]]
    ):
        self._deps = set()
        for d in deps:
            if type(d) is str:

                logging.info(f"Adding dep {d}")
                matches = re.match(r"(.*):(.+)", d)
                if not matches:
                    raise AttributeError(f"Error parsing dep {d} as a bazel dependency")
                location = matches.group(1)
                name = matches.group(2)
                (location, name) = d.split(":")
                bazDep = getObject(BazelExternalDep, name, location)
                self._deps.add(bazDep)
            else:
                assert not isinstance(d, str)
                self._deps.add(d)
        return self._deps

    def setSkipWrapping(self, skipWrapping: bool):
        self.skipWrapping = skipWrapping

    def setHdrs(self, hdrs: List[str]):
        self.hdrs = hdrs

    def setSystemProvided(self):
        self.system_provided = 1

    def setStaticLibrarys(self, staticLibrary: str):
        self.staticLibrary = staticLibrary

    def setSharedLibrarys(self, sharedLibrary: str):
        self.sharedLibrary = sharedLibrary

    def setLocation(self, location: str):
        self.location = location

    def setPhysicalLocation(self, location: str):
        self.physicalLocation = location

    def __eq__(self, other: object) -> bool:
        assert isinstance(other, BazelCCImport) or isinstance(other, BaseBazelTarget)
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)

    def __lt__(self, other: "BazelCCImport") -> bool:
        return self.name < other.name

    def __repr__(self) -> str:
        return f"cc_import {self.name}"

    def getGlobalImport(self) -> str:
        return ""

    def getAllHeaders(self, deps_only=False):
        # cc_import have headers but we don't include them in the upper target
        return set()

    def replaceFirst(self, txt: str) -> str:
        if len(txt) > 0:
            return f"_{txt[1:]}"
        else:
            return txt

    def getAllDeps(self, deps_only=False):
        # Return an empty list, the deps of a cc_import are not propagated
        return []

    def asBazel(self, _flags: CompilationFlags) -> BazelTargetStrings:
        output = {}
        dirs: Set[str] = set()
        val = "[]"
        ret = []

        if self.alias is not None:
            ret.append("alias(")
            ret.append(f'    name = "{self.name}",')
            ret.append(f'    actual = "{self.alias}",')
            ret.append('    tags = ["manual"],')
            ret.append('    visibility = ["//visibility:public"],')
            ret.append(")")
            output[self.name] = ret
            return output


        if len(self.hdrs) > 1:
            # let's iterate on self.hdrs and put the files with the same suffix in the same array
            byExt: Dict[str, List[str]] = {}
            globs = []
            for h in self.hdrs:
                ext = h.split(".")[-1]
                if ext not in byExt:
                    byExt[ext] = []
                byExt[ext].append(h)

            for k, v in byExt.items():
                common = sorted(findCommonPaths(v))
                globs.extend([f'"_{globifyPath(c, k)[1:]}"' for c in common])
                for c in common:
                    dirs.add(f'"_{c[1:]}"')
            if len(globs) > 1:
                sep = ",\n        "
                val = f"glob([\n        {sep.join(globs)},\n    ])"
            else:
                val = f"glob([{globs[0]}])"

        elif len(self.hdrs) == 1 and len(self.hdrs[0]) > 0:
            val = f'["_{self.hdrs[0][1:]}"]'
            v2 = f"_{'/'.join(self.hdrs[0][1:].split(os.path.sep)[:-1])}"
            if v2 != "_usr/include" and v2 != "_usr/local/include":
                dirs = set([f'"{v2}"'])

        # Overide the dirs if includes was specified on the cc_import
        if self.includes is not None:
            if len(self.includes) == 1:
                dirs = set([f'"_{d[1:]}"' for d in self.includes])
            else:
                dirs = set([f'"_{d[1:]}"' for d in self.includes])

        if not self.skipWrapping:
            ret.append("cc_library(")
            ret.append(f'    name = "{self.name}",')
            if len(dirs) > 1:
                dirs_str = (
                    "\n"
                    + ",\n".join(sorted([f"        {d}" for d in dirs]))
                    + ",\n    "
                )
            else:
                dirs_str = ",\n".join(sorted([f"{d}" for d in dirs]))
            ret.append(f"    includes = [{dirs_str}],")
            ret.append('    visibility = ["//visibility:public"],')
            ret.append(f'    deps = [":raw_{self.name}"],')
            ret.append(")")
            ret.append("")

            output[self.name] = ret
            ret = []
            # Prefix for the cc_import library, if we wrap we need to add a prefix to avoid collisions
            prefix = "raw_"
        else:
            prefix = ""

        ret.append("cc_import(")
        ret.append(f'    name = "{prefix}{self.name}",')
        # buildifier seems to want 2 spaces ..
        ret.append(f"    hdrs = {val},")
        if self.system_provided:
            ret.append(f'    system_provided = "{self.system_provided}",')
            if self.sharedLibrary is not None:
                ret.append(
                    f'    interface_library = "{self.replaceFirst(self.sharedLibrary)}",'
                )
        else:
            if self.sharedLibrary is not None:
                ret.append(
                    f'    shared_library = "{self.replaceFirst(self.sharedLibrary)}",'
                )
        if self.staticLibrary is not None:
            ret.append(
                f'    static_library = "{self.replaceFirst(self.staticLibrary)}",'
            )
        ret.append('    visibility = ["//visibility:public"],')
        if len(self.deps) > 0:
            ret.append("    deps = [")
            for d in sorted(self.deps):
                if d.location == self.location:
                    ret.append(f'        "{d.targetName()}",')
                else:
                    ret.append(f'        "{d.location}{d.targetName()}",')
            ret.append("    ],")
        ret.append(")")

        output[f"raw_{self.name}"] = ret
        return output

    def targetName(self) -> str:
        if self.name.startswith(":"):
            return f"{self.name}"
        else:
            return f":{self.name}"


PostProcess = Callable[[List[str]], List[str]]

from itertools import combinations

def find_common_subsets(arrays: List[Set[T]]) -> List[Set[T]]:
    n = len(arrays)
    common_sets = {}

    lowerBound = int(n * 0.95)
    logging.info(f"Lower bound is {lowerBound}")
    logging.info(range(lowerBound, n))
    # Check for common elements in all possible combinations of arrays
    for r in range(lowerBound, n + 1):  # At least 2 arrays should have common items
        for subset in combinations(range(n), r):
            intersect_set = set(arrays[subset[0]])
            for index in subset[1:]:
                intersect_set.intersection_update(arrays[index])

            if intersect_set:
                common_sets[frozenset(subset)] = intersect_set

    logging.info(f"Common sets {common_sets}")

    # Deduplicate: Remove subsets that are already covered in larger sets
    unique_results = {}
    for key, value in common_sets.items():
        if not any(value < common_sets[other_key] for other_key in common_sets if key != other_key):
            unique_results[key] = value

    return list(unique_results.values())

def find_common_subset(sets: List[Set[T]]) -> Set[T]:
    common = set.intersection(*sets)

    return common


class BazelBuild:
    def __init__(self: "BazelBuild", prefix: str):
        self.bazelTargets: Set[Union["BaseBazelTarget", "BazelCCImport"]] = set()
        self.prefix = prefix
        self.postProcess: Dict[str, PostProcess] = {}
        self.commonFlags: Dict[str, CompilationFlags] = {}
        self.additionalBazelHeaders: Dict[str, List[str]] = {}

    def setCommonFlags(self, commonFlags: Dict[str, CompilationFlags]):
        self.commonFlags = commonFlags

    def setAdditionalBazelHeaders(self, headers: Dict[str,List[str]]):
        self.additionalBazelHeaders = headers

    def cleanup(self: "BazelBuild") -> None:
        for type in [ "cc_binary", "cc_library", "cc_test" ]:

            allCopt: List[Set[str]] = []
            for t in self.bazelTargets:
                if isinstance(t, BazelTarget):
                    allCopt.append(t.copts)

            inCommon = find_common_subset(allCopt)
            logging.info(f"In common {inCommon}")

    def addPostProcess(
        self, targetName: str, targetLocation: str, postProcessCallback: PostProcess
    ):
        self.postProcess[f"{targetName}{targetLocation}"] = postProcessCallback

    def genBazelBuildContent(self) -> Dict[str, str]:
        ret: Dict[str, str] = {}
        topContent: Dict[str, Set[str]] = {}
        if self.prefix.endswith("/"):
            prefix = self.prefix[:-1]
        else:
            prefix = self.prefix
        helper_include = {f'load("//{prefix}:helpers.bzl", "add_bazel_out_prefix")'}

        content: Dict[str, List[str]] = {}
        lastLocation = None
        targets = set(self.bazelTargets)
        for t in sorted(targets):
            try:
                if t.location.startswith("@"):
                    assert isinstance(t, BazelCCImport)
                    location = t.physicalLocation
                else:
                    location = t.location
                commonLocationFlags = self.commonFlags.get(location, {})
                body = content.get(location, [])
                body.append(f"# Location {location}")
                for k, v2 in t.asBazel(commonLocationFlags).items():
                    # Do post processing here
                    if self.postProcess.get(f"{k}{location}"):
                        v2 = self.postProcess[f"{k}{location}"](v2)
                    body.extend(v2)
                content[location] = body
                top = topContent.get(location)
                if not top:
                    top = set()
                top.add(t.getGlobalImport())
                if not t.location.startswith("@"):
                    top.update(helper_include)
                if self.additionalBazelHeaders.get(location):
                    top.update(self.additionalBazelHeaders[location])
                topContent[location] = top
                lastLocation = location
            except Exception as e:
                logging.error(f"While generating Bazel content for {t.name}: {e}")
                raise
            if lastLocation is not None:
                content[lastLocation].append("")
        for k, v in topContent.items():
            topStanza = list(filter(lambda x: x != "", v))
            if len(topStanza) > 0:
                # Force empty line

                sort_function = cmp_to_key(compare_imports)
                topStanza = sorted(topStanza, key=sort_function)
                topStanza.append("")
                topStanza.append("")
            logging.info(f"Top content is {topStanza}")
            ret[k] = "\n".join(topStanza)

        for k, v2 in content.items():
            # Add some scaffolding for common options that could be easily tweaked
            vals = []
            flags_n_opts = self.commonFlags.get(k, {})
            for c in ["copts", "defines", "linkopts"]:
                flags = flags_n_opts.get(c, set())
                if isinstance(flags, str):
                    vals.append(f"common_{c} = {flags}\n")
                elif len(flags):
                    vals.append(f"common_{c} = [")
                    for flag in sorted(flags):
                        vals.append(f"    {flag}")
                    vals.append("]\n")
            vals.extend(v2)
            ret[k] += "\n".join(vals)
        return ret


@total_ordering
class BaseBazelTarget(object):
    def __init__(self, type: str, name: str, location: str):
        self.type = type
        self.name = name
        self.location = location
        self.neededGeneratedFiles: set[str] = set()
        self.hdrs: set["BaseBazelTarget"] = set()
        self.deps: set[Union["BaseBazelTarget", BazelCCImport]] = set()

    def depName(self):
        return self.name

    def targetName(self) -> str:
        if self.name.startswith(":"):
            return f"{self.name}"
        else:
            return f":{self.name}"

    def getGlobalImport(self) -> str:
        return ""

    def __hash__(self) -> int:
        return hash(self.type + self.name)

    def __eq__(self, other: object) -> bool:
        assert isinstance(other, BazelCCImport) or isinstance(other, BaseBazelTarget)
        return self.name == other.name

    def __lt__(self, other: "BaseBazelTarget") -> bool:
        return self.name < other.name

    def addSrc(self, target: "BaseBazelTarget"):
        raise NotImplementedError(f"addSrc not implemented for {self.__class__}")

    def asBazel(self, flags: CompilationFlags) -> BazelTargetStrings:
        raise NotImplementedError

    def addDep(self, target: Union["BaseBazelTarget", BazelCCImport]):
        raise NotImplementedError

    @cache
    def getAllHeaders(self, deps_only=False) -> Set["BaseBazelTarget"]:
        ret = set()
        if not deps_only:
            ret.update(self.hdrs)
        for d in self.deps:
            try:
                ret.update(d.getAllHeaders())
            except AttributeError:
                logging.warn(f"Can't get headers for {d.name}")
                raise
        return ret

    @cache
    def getAllDeps(
        self, deps_only=False
    ) -> Set[Union["BaseBazelTarget", BazelCCImport]]:
        ret = set()
        if not deps_only:
            ret.update(self.deps)
        for d in self.deps:
            try:
                ret.update(d.getAllDeps())
            except AttributeError:
                logging.warn(f"Can't get deps for {d.name}")
                raise
        logging.info(f"Returning for {self.name} {len(ret)} deps")
        return ret


@total_ordering
class ExportedFile(BaseBazelTarget):
    def __init__(self, name: str, location: str):
        super().__init__("exports_file", name, location)

    def __str__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.name == other
        if isinstance(other, ExportedFile):
            return self.name == other.name
        if isinstance(other, BazelGenRuleTargetOutput):
            return self.name == other.targetName()
        return False

    def __hash__(self) -> int:
        if self.name.startswith(":"):
            return hash(self.name[1:])
        return hash(self.name)


@total_ordering
class BazelTarget(BaseBazelTarget):
    def __init__(self, type: str, name: str, location: str):
        super().__init__(type, name, location)
        self.srcs: set[BaseBazelTarget] = set()
        self.includeDirs: set[IncludeDir] = set()
        self.addPrefixIfRequired: bool = True
        self.copts: set[str] = set()
        self.defines: set[str] = set()
        self.data: set[BaseBazelTarget] = set()

    def addCopt(self, opt: str):
        self.copts.add(opt)

    def addDefine(self, define: str):
        self.defines.add(define)

    def addData(self, target: BaseBazelTarget):
        self.data.add(target)

    def depName(self):
        name = self.name
        if self.type == "cc_library":
            name = name.replace("/", "_")
        if self.type == "cc_library" or self.type == "cc_shared_library":
            if not name.startswith("lib") and self.addPrefixIfRequired:
                name = f"lib{name}"
            elif self.addPrefixIfRequired:
                name = f"lib{name.replace('_lib', '')}"
            else:
                name = name
            name = name.replace(".a", "")
            name = name.replace(".so", "")
        elif self.type == "cc_test":
            name = f"test_{name}"
            if name.endswith("_test"):
                name = name[:-5]
        return name

    def targetName(self):
        return f":{self.depName()}"

    def addDep(self, target: Union["BaseBazelTarget", BazelCCImport]):
        self.deps.add(target)

    def addIncludeDir(self, includeDir: IncludeDir):
        self.includeDirs.add(includeDir)

    def addNeededGeneratedFiles(self, filename: str):
        self.neededGeneratedFiles.add(filename)

    def addHdr(self, target: BaseBazelTarget, includeDir: Optional[IncludeDir] = None):
        if "//" in target.name:
            logging.warning(f"There is a double / in {target.name}, fix your code")
            target.name = target.name.replace("//", "/")
        self.hdrs.add(target)
        if includeDir is not None:
            self.includeDirs.add(includeDir)

    def addSrc(self, target: BaseBazelTarget):
        self.srcs.add(target)

    def __repr__(self) -> str:
        base = f"{self.type}({self.name})"
        if len(self.srcs):
            srcs = f" SRCS[{' '.join([str(s) for s in self.srcs])}]"
            base += srcs
        if len(self.hdrs):
            hdrs = f" HDRS[{' '.join([str(s) for s in self.hdrs])}]"
            base += hdrs
        if len(self.deps):
            deps = f" DEPS[{' '.join([str(d.targetName()) for d in self.deps])}]"
            base += deps
        return base

    def asBazel(self, commonFlags:CompilationFlags) -> BazelTargetStrings:
        ret = []
        ret.append(f"{self.type}(")
        name = self.depName().replace(":", "")
        ret.append(f'    name = "{name}",')
        deps_headers = set(self.getAllHeaders(deps_only=True))
        deps_deps = set(self.getAllDeps(deps_only=True))
        deps: Set[Union[BaseBazelTarget, BazelCCImport]] = set()
        headers = []
        data: List[BaseBazelTarget] = list(self.data)
        for d in self.deps:
            if d not in deps_deps:
                deps.add(d)
        for h in self.hdrs:
            if h not in deps_headers:
                if (
                    h.name.endswith(".h")
                    or h.name.endswith(".hpp")
                    or h.name.endswith(".tcc")
                ):
                    headers.append(h)
                else:
                    if self.type != "cc_library":
                        logging.warn(
                            f"There is some kind of header that didn't match .h/.hpp/.tcc adding to data but it's likely to not work well"
                        )
                        data.append(h)

        sources = [f for f in self.srcs]
        copts = set()
        copts.update(self.copts)
        for dir in list(self.includeDirs):
            # The second element IncludeDir is a flag to indicate if the header is generated
            # and if so we need to add the bazel-out prefix to the -I option
            if dir[1]:
                dirName = (
                    f'add_bazel_out_prefix("{self.location + os.path.sep +dir[0]}")'
                )
            else:
                dirName = f'"{dir[0]}"'
            copts.add(f'"-I{{}}".format({dirName})')
        # FIXME for the moment move defines to copts so that they are not propagated to
        # the targets that depends on it
        for define in self.defines:
            define = define.replace('"', "")
            copts.add(f'"-D{define}"')
        self.defines = set()
        if self.type in ("cc_library", "cc_binary", "cc_test"):
            linkopts = ["keep"]
        else:
            linkopts = []
        textOptions: Dict[str, List[str]] = {}

        hm: Dict[str, List[Any]] = {
            "srcs": sources,
            "hdrs": headers,
            "copts": list(copts),
            "defines": list(self.defines),
            "linkopts": linkopts,
            "data": data,
            "deps": list(deps),
        }
        if self.type == "cc_binary" or self.type == "cc_test":
            del hm["hdrs"]
            sources.extend(headers)
            headers = []

        for k, v in hm.items():
            if len(v) == 0:
                continue
            if isinstance(v[0], str):
                if len(v) > 0:
                    if v[0] == "keep":
                        v = []
                    if commonFlags.get(k):
                        ret.append(f"    {k} = common_{k} + [")
                    else:
                        ret.append(f"    {k} = [")
                    for to in sorted(v):
                        ret.append(f"        {to},")
                    ret.append("    ],")
            else:
                ret.append(f"    {k} = [")

                def __getPrefix(d: BaseBazelTarget | BazelCCImport):
                    return _getPrefix(d, self.location)

                def cmp_deps(a, b):
                    return compare_deps(a, b, __getPrefix)

                sort_function = cmp_to_key(cmp_deps)
                for d in sorted(v, key=sort_function):
                    pathPrefix = __getPrefix(d)
                    ret.append(f'        "{pathPrefix}{d.targetName()}",')
                ret.append("    ],")
        ret.append(")")

        return {name: ret}


class BazelGenRuleTarget(BaseBazelTarget):
    def __init__(self, name: str, location: str):
        super().__init__("genrule", name, location)
        self.cmd = ""
        self.outs: set[BazelGenRuleTargetOutput] = set()
        self.srcs: set[BaseBazelTarget] = set()
        self.data: set[BaseBazelTarget] = set()
        self.tools: set[BaseBazelTarget] = set()
        # We most probably don't want to do remote execution as we are running things from the
        # filesystem
        self.local: bool = True
        self.aliases: Dict[str, str] = {}

    def addSrc(self, target: BaseBazelTarget):
        self.srcs.add(target)

    def addOut(self, name: str, alias: Optional[str] = None):
        if alias:
            self.aliases[alias] = name
        else:
            target = BazelGenRuleTargetOutput(name, self.location, self)
            self.outs.add(target)

    def addTool(self, target: BaseBazelTarget):
        self.tools.add(target)

    def asBazel(self, _flags: CompilationFlags) -> BazelTargetStrings:
        ret = []
        ret.append(f"{self.type}(")
        ret.append(f'    name = "{self.name}",')
        hm: Dict[
            str, Union[str, Set[BaseBazelTarget], Set[BazelGenRuleTargetOutput]]
        ] = {
            "srcs": self.srcs,
            "outs": self.outs,
            "cmd": self.cmd,
            "local": str(self.local),
            "tools": self.tools,
        }
        len(self.outs)
        for k, v in hm.items():
            if isinstance(v, str):
                if k == "cmd":
                    ret.append(f'    {k} = """{v}""",')
                else:
                    ret.append(f"    {k} = {v},")
            elif len(v) > 0:
                ret.append(f"    {k} = [")
                for d in sorted(v):
                    pathPrefix = (
                        f"//{d.location}" if d.location != self.location else ""
                    )
                    ret.append(f'        "{pathPrefix}{d.targetName()}",')
                ret.append("    ],")
        ret.append(")")

        return {self.name: ret}

    def getOutputs(
        self, name: str, stripedPrefix: Optional[str] = None
    ) -> List["BazelGenRuleTargetOutput"]:
        if stripedPrefix:
            name = name.replace(stripedPrefix, "")
        if self.aliases.get(name) is not None:
            logging.info(f"Found alias {name} to {self.aliases[name]}")
            name = self.aliases[name]
        if name not in self.outs:
            raise ValueError(
                f"Output {name} didn't exists on genrule {self.name} {self.aliases}"
            )
        regex = r".*?/?([^/]*)\.[h|cc|cpp|hpp|c]"
        match = re.match(regex, name)
        if 0 and match:
            regex2 = rf".*?{match.group(1)}\.[h|cc|cpp|hpp|c]"
            outs = [v for v in self.outs if re.match(regex2, v.name)]
        else:
            outs = [v for v in self.outs if v.name == name]

        return outs


class BazelCCProtoLibrary(BaseBazelTarget):
    def __init__(self, name: str, location: str):
        super().__init__("cc_proto_library", name, location)

    def addDep(self, dep: Union[BaseBazelTarget, BazelCCImport]):
        assert isinstance(dep, BazelProtoLibrary) or isinstance(dep, BazelExternalDep)
        self.deps.add(dep)

    def asBazel(self, _flags: CompilationFlags) -> BazelTargetStrings:
        ret = []
        ret.append(f"{self.type}(")
        ret.append(f'    name = "{self.name}",')
        if len(self.deps) > 0:
            ret.append("    deps = [")
            for d in sorted(self.deps):
                pathPrefix = ""
                if d.location.startswith("@"):
                    pathPrefix = d.location
                else:
                    pathPrefix = (
                        f"//{d.location}" if d.location != self.location else ""
                    )
                ret.append(f'        "{pathPrefix}{d.targetName()}",')
            ret.append("    ],")
        ret.append(")")

        return {self.name: ret}


class BazelGRPCCCProtoLibrary(BaseBazelTarget):
    def __init__(self, name: str, location: str):
        super().__init__("cc_grpc_library", name, location)
        self.srcs: Set[BaseBazelTarget] = set()
        self.deps.add(BazelExternalDep("grpc++", "@com_github_grpc_grpc//"))

    def addDep(self, dep: Union[BaseBazelTarget, BazelCCImport]):
        assert isinstance(dep, BazelCCProtoLibrary)
        self.deps.add(dep)

    def addSrc(self, dep: BaseBazelTarget):
        assert isinstance(dep, BazelProtoLibrary)
        self.srcs.add(dep)

    def getGlobalImport(self):
        return 'load("@com_github_grpc_grpc//bazel:cc_grpc_library.bzl", "cc_grpc_library")'

    def asBazel(self, _flags: CompilationFlags) -> BazelTargetStrings:
        ret = []
        ret.append(f"{self.type}(")
        ret.append(f'    name = "{self.name}",')
        assert len(self.deps) > 0
        hm: Dict[str, Union[bool, Set[Any]]] = {
            "srcs": self.srcs,
            "grpc_only": True,
            "deps": self.deps,
        }
        for k, v in hm.items():
            if isinstance(v, bool):
                ret.append(f"    {k} = {v},")
            elif len(v) > 0:
                ret.append(f"    {k} = [")

                def __getPrefix(d: BaseBazelTarget | BazelCCImport):
                    return _getPrefix(d, self.location)

                def cmp_deps(a, b):
                    return compare_deps(a, b, __getPrefix)

                sort_function = cmp_to_key(cmp_deps)

                for d in sorted(v, key=sort_function):
                    if d.location.startswith("@"):
                        pathPrefix = d.location
                    else:
                        pathPrefix = (
                            f"//{d.location}" if d.location != self.location else ""
                        )
                    ret.append(f'        "{pathPrefix}{d.targetName()}",')
                ret.append("    ],")
        ret.append(")")

        return {self.name: ret}


class BazelProtoLibrary(BaseBazelTarget):
    def __init__(
        self, name: str, location: str, stripImportPrefix: Optional[str] = None
    ):
        super().__init__(
            "proto_library",
            name,
            location,
        )
        self.stripImportPrefix = stripImportPrefix
        self.srcs: Set[BaseBazelTarget] = set()

    def getGlobalImport(self):
        return 'load("@rules_proto//proto:defs.bzl", "proto_library")'

    def addSrc(self, target: BaseBazelTarget):
        self.srcs.add(target)

    def addDep(self, target: Union[BaseBazelTarget, BazelCCImport]):
        assert isinstance(target, BaseBazelTarget)
        self.deps.add(target)

    def asBazel(self, _flags: CompilationFlags) -> BazelTargetStrings:
        ret = []
        ret.append(f"{self.type}(")
        ret.append(f'    name = "{self.name}",')

        hm: Dict[str, Union[Set[Any], str]] = {"srcs": self.srcs}
        if self.stripImportPrefix is not None:
            hm["strip_import_prefix"] = self.stripImportPrefix
        hm["deps"] = self.deps
        for k, v in hm.items():
            if isinstance(v, str):
                ret.append(f'    {k} = "{v}",')
            elif len(v) > 0:
                ret.append(f"    {k} = [")

                def __getPrefix(d: BaseBazelTarget | BazelCCImport):
                    return _getPrefix(d, self.location)

                def cmp_deps(a, b):
                    return compare_deps(a, b, __getPrefix)

                for d in sorted(v, key=cmp_to_key(cmp_deps)):
                    if d.location.startswith("@"):
                        pathPrefix = d.location
                    else:
                        pathPrefix = (
                            f"//{d.location}" if d.location != self.location else ""
                        )
                    ret.append(f'        "{pathPrefix}{d.targetName()}",')
                ret.append("    ],")
        ret.append(")")

        return {self.name: ret}


@total_ordering
class BazelExternalDep(BaseBazelTarget):
    def __init__(self, name: str, location: str):
        super().__init__("external", name, location)

    def asBazel(self, _flags: CompilationFlags) -> BazelTargetStrings:
        return {}


@total_ordering
class BazelGenRuleTargetOutput(BaseBazelTarget):
    def __repr__(self):
        return f"genrule_output {self.name}"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.name == other
        if isinstance(other, BazelGenRuleTargetOutput):
            return self.name == other.name
        if isinstance(other, BaseBazelTarget):
            return self.name == other.name
        return False

    def __hash__(self) -> int:
        return hash(self.name)

    def __init__(
        self,
        name: str,
        location: str,
        genrule: BazelGenRuleTarget,
    ):
        super().__init__("genrule_output", f"{genrule.targetName()}_{name}", location)
        self.rule = genrule
        self.name = name

    def asBazel(self, flags: CompilationFlags) -> BazelTargetStrings:
        return self.rule.asBazel(flags)

    def getAllHeaders(self, deps_only=False):
        if self.name.endswith(".h"):
            return set(self.name)
        return set()


class PyBinaryBazelTarget(BaseBazelTarget):
    def __init__(self, name: str, location: str):
        super().__init__("py_binary", name, location)
        self.main = ""
        self.srcs: set[BaseBazelTarget] = set()
        self.data: set[BaseBazelTarget] = set()

    def asBazel(self, _flags: CompilationFlags) -> BazelTargetStrings:
        ret = []
        ret.append(f"{self.type}(")
        ret.append(f'    name = "{self.name}",')
        sources = [f for f in self.srcs]
        if len(sources) > 0:
            ret.append("    srcs = [")
            for f in sorted(sources):
                ret.append(f'        "{f.targetName()}",')
            ret.append("    ],")
        ret.append(f'    main = "{self.main}",')
        ret.append(")")

        return {self.name: ret}

    def addSrc(self, target: BaseBazelTarget):
        self.srcs.add(target)


class ShBinaryBazelTarget(BaseBazelTarget):
    def __init__(self, name: str, location: str):
        super().__init__("sh_binary", name, location)
        self.srcs: set[BaseBazelTarget] = set()
        self.data: set[BaseBazelTarget] = set()

    def asBazel(self, _flags: CompilationFlags) -> BazelTargetStrings:
        ret = []
        ret.append(f"{self.type}(")
        ret.append(f'    name = "{self.name}",')
        sources = [f for f in self.srcs]
        if len(sources) > 0:
            ret.append("    srcs = [")
            for f in sorted(sources):
                ret.append(f'        "{f.targetName()}",')
            ret.append("    ],")
        ret.append(")")

        return {self.name: ret}

    def addSrc(self, target: BaseBazelTarget):
        self.srcs.add(target)


bazelcache: Dict[str, Any] = {}


def getObject(cls: Type[T], *kargs) -> T:
    key = f"{cls}" + " ".join(kargs)
    obj = bazelcache.get(key)
    if obj:
        logging.debug(f"Cache hit for {key} {type(obj)}")
        assert isinstance(obj, cls)
        return obj
    obj = cls(*kargs)  # type: ignore
    bazelcache[key] = obj
    return obj

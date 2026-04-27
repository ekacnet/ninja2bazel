import logging
import os
import re
import shlex
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set


PLACEHOLDER_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)@|\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
SET_RE_TEMPLATE = r"set\s*\(\s*{name}(?:\s|\))"


@dataclass(frozen=True)
class ConfigureFile:
    source: str
    output: str
    value_files: tuple[str, ...]


def _normalize_path(path: str) -> str:
    return os.path.normpath(path).replace(os.path.sep, "/")


def _resolve_cmake_path(path: str, source_dir: str, binary_dir: str) -> str:
    replacements = {
        "${CMAKE_CURRENT_SOURCE_DIR}": source_dir,
        "${CMAKE_SOURCE_DIR}": source_dir,
        "${PROJECT_SOURCE_DIR}": source_dir,
        "${CMAKE_CURRENT_BINARY_DIR}": binary_dir,
        "${CMAKE_BINARY_DIR}": binary_dir,
        "${PROJECT_BINARY_DIR}": binary_dir,
    }
    for key, value in replacements.items():
        path = path.replace(key, value)
    if not os.path.isabs(path):
        path = os.path.join(source_dir, path)
    return os.path.normpath(path)


def _path_tail(path: str) -> str:
    match = re.search(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}/(.+)", path)
    if match:
        return match.group(1)
    return path


def _resolve_existing_source(path: str, source_dir: str, resolved: str) -> str:
    if os.path.exists(resolved):
        return resolved

    tail = _path_tail(path)
    matches = []
    for current, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        for filename in files:
            candidate = os.path.join(current, filename)
            if _normalize_path(candidate).endswith(_normalize_path(tail)):
                matches.append(candidate)

    if len(matches) == 1:
        return os.path.normpath(matches[0])
    if len(matches) > 1:
        logging.fatal(
            f"Could not resolve configure_file source {path}; "
            f"found multiple matches: {', '.join(sorted(matches))}"
        )
        raise SystemExit(-1)
    return resolved


def _parse_configure_file_args(line: str) -> Optional[List[str]]:
    match = re.search(r"configure_file\s*\((.*)\)", line)
    if not match:
        return None
    lexer = shlex.shlex(match.group(1), posix=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    args = list(lexer)
    if len(args) < 2:
        logging.fatal(f"Invalid configure_file entry: {line.rstrip()}")
        raise SystemExit(-1)
    return args


def _find_placeholders(template_path: str) -> Set[str]:
    try:
        with open(template_path, "r") as f:
            contents = f.read()
    except OSError as exc:
        logging.fatal(f"Cannot read configure_file template {template_path}: {exc}")
        raise SystemExit(-1)
    return {match.group(1) or match.group(2) for match in PLACEHOLDER_RE.finditer(contents)}


def _iter_candidate_files(rootdir: str) -> Iterable[str]:
    ignored_dirs = {".git", "bazel-bin", "bazel-out", "bazel-testlogs"}
    for current, dirs, files in os.walk(rootdir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        for filename in files:
            if filename.endswith((".cmake", ".txt", ".in", ".h.cmake")) or filename == "CMakeLists.txt":
                yield os.path.join(current, filename)


def _find_value_files(rootdir: str, placeholders: Set[str], template_path: str) -> tuple[str, ...]:
    found: Dict[str, Set[str]] = {placeholder: set() for placeholder in placeholders}
    for path in _iter_candidate_files(rootdir):
        if os.path.normpath(path) == os.path.normpath(template_path):
            continue
        try:
            with open(path, "r", errors="ignore") as f:
                contents = f.read()
        except OSError:
            continue
        for placeholder in placeholders:
            if re.search(SET_RE_TEMPLATE.format(name=re.escape(placeholder)), contents):
                found[placeholder].add(path)

    missing = sorted([placeholder for placeholder, paths in found.items() if not paths])
    if missing:
        logging.fatal(
            "Missing CMake definitions for configure_file placeholders "
            f"{', '.join(missing)} in {template_path}"
        )
        raise SystemExit(-1)

    files = set()
    for paths in found.values():
        files.update(paths)
    return tuple(sorted(files))


def parse_configure_files_list(
    filename: Optional[str],
    source_dir: str,
    binary_dir: str,
) -> Dict[str, ConfigureFile]:
    if not filename:
        return {}
    if not os.path.exists(filename):
        logging.fatal(f"Configure files list {filename} does not exist")
        raise SystemExit(-1)

    ret: Dict[str, ConfigureFile] = {}
    with open(filename, "r") as f:
        lines = f.readlines()
    for line in lines:
        args = _parse_configure_file_args(line)
        if args is None:
            continue
        source = _resolve_cmake_path(args[0], source_dir, binary_dir)
        source = _resolve_existing_source(args[0], source_dir, source)
        output = _resolve_cmake_path(args[1], source_dir, binary_dir)
        placeholders = _find_placeholders(source)
        value_files = _find_value_files(source_dir, placeholders, source)
        entry = ConfigureFile(source=source, output=output, value_files=value_files)
        ret[_normalize_path(output)] = entry
        ret[_normalize_path(os.path.relpath(output, binary_dir))] = entry
    return ret


def find_configure_file(
    configure_files: Dict[str, ConfigureFile],
    output: str,
    binary_dir: str,
) -> Optional[ConfigureFile]:
    if not configure_files:
        return None
    candidates = [
        output,
        output.replace("<pregenerated>/", ""),
        output.replace("pregenerated/", "", 1),
    ]
    if not os.path.isabs(output):
        candidates.append(os.path.join(binary_dir, output.replace("pregenerated/", "", 1)))
    normalized = [_normalize_path(candidate) for candidate in candidates]
    for candidate in normalized:
        if candidate in configure_files:
            return configure_files[candidate]
    for key, entry in configure_files.items():
        if any(key.endswith(candidate) or candidate.endswith(key) for candidate in normalized):
            return entry
    return None

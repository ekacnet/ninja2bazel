import logging
import os
import re
import shlex
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set


PLACEHOLDER_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)@|\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
CMAKE_DEFINE_RE = re.compile(r"^\s*#\s*cmakedefine(?:01)?\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
SET_RE_TEMPLATE = r"set\s*\(\s*{name}(?:\s|\))"


@dataclass(frozen=True)
class ConfigureFile:
    source: str
    output: str
    value_files: tuple[str, ...]
    variables: Dict[str, str]


def parse_configure_vars(configure_vars: Optional[List[str]]) -> Dict[str, str]:
    ret: Dict[str, str] = {}
    for configure_var in configure_vars or []:
        if "=" not in configure_var:
            logging.fatal(
                f"Configure variable {configure_var} is not in the form key=value"
            )
            raise SystemExit(-1)
        key, value = configure_var.split("=", 1)
        if not key:
            logging.fatal(f"Configure variable {configure_var} has an empty key")
            raise SystemExit(-1)
        ret[key] = value
    return ret


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


def _find_placeholders(template_path: str) -> tuple[Set[str], Set[str]]:
    try:
        with open(template_path, "r") as f:
            contents = f.read()
    except OSError as exc:
        logging.fatal(f"Cannot read configure_file template {template_path}: {exc}")
        raise SystemExit(-1)
    required = {match.group(1) or match.group(2) for match in PLACEHOLDER_RE.finditer(contents)}
    optional = {match.group(1) for match in CMAKE_DEFINE_RE.finditer(contents)}
    return required, optional


def _iter_candidate_files(rootdir: str) -> Iterable[str]:
    ignored_dirs = {".git", "bazel-bin", "bazel-out", "bazel-testlogs"}
    for current, dirs, files in os.walk(rootdir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        for filename in files:
            if filename.endswith((".cmake", ".txt", ".in", ".h.cmake")) or filename == "CMakeLists.txt":
                yield os.path.join(current, filename)


def _find_value_files(
    rootdir: str,
    placeholders: Set[str],
    template_path: str,
    fail_on_missing: bool = True,
) -> tuple[str, ...]:
    if not placeholders:
        return ()

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
    if missing and fail_on_missing:
        logging.fatal(
            "Missing CMake definitions for configure_file placeholders "
            f"{', '.join(missing)} in {template_path}"
        )
        raise SystemExit(-1)

    files = set()
    for paths in found.values():
        files.update(paths)
    return tuple(sorted(files))


def _current_cmake_dirs(filename: str, source_dir: str, binary_dir: str) -> tuple[str, str]:
    source_dir_abs = os.path.abspath(source_dir)
    binary_dir_abs = os.path.abspath(binary_dir)
    cmake_dir = os.path.dirname(os.path.abspath(filename))
    try:
        if os.path.commonpath([source_dir_abs, cmake_dir]) != source_dir_abs:
            return source_dir, binary_dir
    except ValueError:
        return source_dir, binary_dir

    rel_dir = os.path.relpath(cmake_dir, source_dir_abs)
    if rel_dir == ".":
        return source_dir, binary_dir
    return cmake_dir, os.path.normpath(os.path.join(binary_dir_abs, rel_dir))


def _configure_output_keys(output: str, binary_dir: str) -> Set[str]:
    keys = {_normalize_path(output)}
    rel_output = output
    if os.path.isabs(output):
        rel_output = os.path.relpath(output, binary_dir)
        keys.add(_normalize_path(rel_output))

    normalized_rel_output = _normalize_path(rel_output)
    if normalized_rel_output.startswith("pregenerated/"):
        keys.add(normalized_rel_output[len("pregenerated/") :])
    else:
        keys.add(f"pregenerated/{normalized_rel_output}")
    return keys


def _uses_cmake_current_dir(path: str) -> bool:
    return (
        "${CMAKE_CURRENT_SOURCE_DIR}" in path
        or "${CMAKE_CURRENT_BINARY_DIR}" in path
    )


def _infer_current_dirs_from_source(
    source_arg: str,
    source: str,
    source_dir: str,
    binary_dir: str,
) -> tuple[str, str]:
    source_abs = _normalize_path(os.path.abspath(source))
    tail = _normalize_path(_path_tail(source_arg))
    if tail and source_abs.endswith(f"/{tail}"):
        source_parent = os.path.normpath(source_abs[: -len(tail)].rstrip("/"))
    else:
        source_parent = os.path.dirname(os.path.abspath(source))
    source_dir_abs = os.path.abspath(source_dir)
    binary_dir_abs = os.path.abspath(binary_dir)
    try:
        if os.path.commonpath([source_dir_abs, source_parent]) != source_dir_abs:
            return source_dir, binary_dir
    except ValueError:
        return source_dir, binary_dir

    rel_dir = os.path.relpath(source_parent, source_dir_abs)
    if rel_dir == ".":
        return source_dir, binary_dir
    return source_parent, os.path.normpath(os.path.join(binary_dir_abs, rel_dir))


def _describe_configure_file(key: str, entry: ConfigureFile, binary_dir: str) -> str:
    return (
        f"key={key}, output={_normalize_path(entry.output)}, "
        f"rel_output={_normalize_path(os.path.relpath(entry.output, binary_dir))}, "
        f"source={_normalize_path(entry.source)}, "
        f"value_files={[ _normalize_path(path) for path in entry.value_files ]}"
    )


def parse_configure_files_list(
    filename: Optional[str],
    source_dir: str,
    binary_dir: str,
    configure_vars: Optional[Dict[str, str]] = None,
    needed_outputs: Optional[Set[str]] = None,
) -> Dict[str, ConfigureFile]:
    if not filename:
        return {}
    if not os.path.exists(filename):
        logging.fatal(f"Configure files list {filename} does not exist")
        raise SystemExit(-1)

    ret: Dict[str, ConfigureFile] = {}
    normalized_needed_outputs = (
        {_normalize_path(output) for output in needed_outputs}
        if needed_outputs is not None
        else None
    )
    with open(filename, "r") as f:
        lines = f.readlines()
    for line in lines:
        args = _parse_configure_file_args(line)
        if args is None:
            continue
        current_source_dir, current_binary_dir = _current_cmake_dirs(
            filename,
            source_dir,
            binary_dir,
        )
        source = _resolve_cmake_path(args[0], current_source_dir, current_binary_dir)
        source = _resolve_existing_source(args[0], source_dir, source)
        if _uses_cmake_current_dir(args[0]) and _uses_cmake_current_dir(args[1]):
            current_source_dir, current_binary_dir = _infer_current_dirs_from_source(
                args[0],
                source,
                source_dir,
                binary_dir,
            )
        output = _resolve_cmake_path(args[1], current_source_dir, current_binary_dir)
        output_keys = _configure_output_keys(output, binary_dir)
        if normalized_needed_outputs is not None and not (
            output_keys & normalized_needed_outputs
        ):
            logging.info(
                "Skipping configure_file entry for output %s because none of its "
                "keys %s are needed; needed output count=%d",
                _normalize_path(output),
                sorted(output_keys),
                len(normalized_needed_outputs),
            )
            continue

        variables = configure_vars or {}
        required_placeholders, optional_placeholders = _find_placeholders(source)
        configured_variable_names = set(variables.keys())
        required_placeholders -= configured_variable_names
        optional_placeholders -= configured_variable_names
        value_files = tuple(
            sorted(
                set(_find_value_files(source_dir, required_placeholders, source))
                | set(
                    _find_value_files(
                        source_dir,
                        optional_placeholders,
                        source,
                        fail_on_missing=False,
                    )
                )
            )
        )
        entry = ConfigureFile(
            source=source,
            output=output,
            value_files=value_files,
            variables=variables,
        )
        ret[_normalize_path(output)] = entry
        ret[_normalize_path(os.path.relpath(output, binary_dir))] = entry
        logging.info(
            "Registered configure_file output %s from source %s with keys %s",
            _normalize_path(output),
            _normalize_path(source),
            sorted(output_keys),
        )
    if filename:
        logging.info(
            "Configured %d configure_file entries from %s",
            len({entry.output for entry in ret.values()}),
            filename,
        )
    return ret


def _log_configure_file_miss(
    configure_files: Dict[str, ConfigureFile],
    output: str,
    binary_dir: str,
    normalized: List[str],
) -> None:
    logging.info(
        "No configure_file matched requested output %s. Tried candidates: %s. "
        "binary_dir=%s. configured entries=%d",
        _normalize_path(output),
        normalized,
        _normalize_path(binary_dir),
        len({entry.output for entry in configure_files.values()}),
    )
    for key, entry in sorted(configure_files.items()):
        logging.info(
            "Configured configure_file did not match %s: %s",
            _normalize_path(output),
            _describe_configure_file(key, entry, binary_dir),
        )


def find_configure_file(
    configure_files: Dict[str, ConfigureFile],
    output: str,
    binary_dir: str,
) -> Optional[ConfigureFile]:
    if not configure_files:
        logging.info(
            "No configure_file entries are configured while looking for %s",
            _normalize_path(output),
        )
        return None
    candidates = [
        output,
        output.replace("<pregenerated>/", ""),
        output.replace("pregenerated/", "", 1),
    ]
    if not os.path.isabs(output):
        candidates.append(os.path.join(binary_dir, output.replace("pregenerated/", "", 1)))
    normalized = [_normalize_path(candidate) for candidate in candidates]
    logging.info(
        "Looking for configure_file match for %s using candidates %s",
        _normalize_path(output),
        normalized,
    )
    for candidate in normalized:
        if candidate in configure_files:
            logging.info(
                "Matched configure_file for %s by exact candidate %s: %s",
                _normalize_path(output),
                candidate,
                _describe_configure_file(candidate, configure_files[candidate], binary_dir),
            )
            return configure_files[candidate]
    for key, entry in configure_files.items():
        if any(key.endswith(candidate) or candidate.endswith(key) for candidate in normalized):
            logging.info(
                "Matched configure_file for %s by suffix key %s: %s",
                _normalize_path(output),
                key,
                _describe_configure_file(key, entry, binary_dir),
            )
            return entry
    _log_configure_file_miss(configure_files, output, binary_dir, normalized)
    return None

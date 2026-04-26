#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

SET_RE = re.compile(
    r"set\(\s*([A-Za-z_][A-Za-z0-9_]*)\s+(.*?)\s*\)",
    re.DOTALL,
)
AT_PLACEHOLDER_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)@")
DOLLAR_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _normalize_value(raw_value: str) -> str:
    value = raw_value.strip()
    if "#" in value:
        value = value.split("#", 1)[0].rstrip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def parse_cmake_definitions(contents: str) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for match in SET_RE.finditer(contents):
        definitions[match.group(1)] = _normalize_value(match.group(2))
    return definitions


def render_template(template: str, definitions: dict[str, str]) -> str:
    def replace_at(match: re.Match[str]) -> str:
        key = match.group(1)
        return definitions.get(key, match.group(0))

    def replace_dollar(match: re.Match[str]) -> str:
        key = match.group(1)
        return definitions.get(key, match.group(0))

    rendered = AT_PLACEHOLDER_RE.sub(replace_at, template)
    return DOLLAR_PLACEHOLDER_RE.sub(replace_dollar, rendered)


def generate_header(
    template_path: Path,
    values_path: Path,
    output_path: Path,
) -> None:
    template = template_path.read_text()
    definitions = parse_cmake_definitions(values_path.read_text())
    rendered = render_template(template, definitions)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render ProtocolVersion.h from CMake template inputs"
    )
    parser.add_argument("template")
    parser.add_argument("values")
    parser.add_argument("output")
    args = parser.parse_args()

    generate_header(Path(args.template), Path(args.values), Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

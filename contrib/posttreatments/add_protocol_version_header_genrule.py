#!/usr/bin/env python3
import argparse
import ast
from pathlib import Path
from typing import Optional

RULE_NAME = "generate_protocol_version_header"
OUTPUT = "pregenerated/flow/include/flow/ProtocolVersion.h"
TEMPLATE = "flow/ProtocolVersion.h.cmake"
VALUES = "flow/ProtocolVersions.cmake"
TOOL = "//contrib/posttreatments:render_protocol_version_header"


def _string_value(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _target_name(call: ast.Call) -> Optional[str]:
    for keyword in call.keywords:
        if keyword.arg == "name":
            return _string_value(keyword.value)
    return None


def _list_string_values(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.List):
        return []
    values = []
    for element in node.elts:
        value = _string_value(element)
        if value is not None:
            values.append(value)
    return values


def _target_already_exists(call: ast.Call) -> bool:
    if _call_name(call) != "genrule":
        return False
    if _target_name(call) == RULE_NAME:
        return True

    for keyword in call.keywords:
        if keyword.arg == "outs" and OUTPUT in _list_string_values(keyword.value):
            return True
    return False


def _make_genrule_expr() -> ast.Expr:
    return ast.Expr(
        value=ast.Call(
            func=ast.Name(id="genrule", ctx=ast.Load()),
            args=[],
            keywords=[
                ast.keyword(arg="name", value=ast.Constant(value=RULE_NAME)),
                ast.keyword(
                    arg="srcs",
                    value=ast.List(
                        elts=[
                            ast.Constant(value=TEMPLATE),
                            ast.Constant(value=VALUES),
                        ],
                        ctx=ast.Load(),
                    ),
                ),
                ast.keyword(
                    arg="outs",
                    value=ast.List(
                        elts=[ast.Constant(value=OUTPUT)],
                        ctx=ast.Load(),
                    ),
                ),
                ast.keyword(
                    arg="tools",
                    value=ast.List(
                        elts=[ast.Constant(value=TOOL)],
                        ctx=ast.Load(),
                    ),
                ),
                ast.keyword(
                    arg="cmd",
                    value=ast.Constant(
                        value=" ".join(
                            [
                                "$(location //contrib/posttreatments:render_protocol_version_header)",
                                "$(location flow/ProtocolVersion.h.cmake)",
                                "$(location flow/ProtocolVersions.cmake)",
                                "$@",
                            ]
                        )
                    ),
                ),
                ast.keyword(
                    arg="visibility",
                    value=ast.List(
                        elts=[ast.Constant(value="//visibility:public")],
                        ctx=ast.Load(),
                    ),
                ),
            ],
        )
    )


def rewrite_build_file_contents(source: str) -> str:
    tree = ast.parse(source)

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if _target_already_exists(node.value):
                return source

    tree.body.append(_make_genrule_expr())
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def rewrite_build_file(path: Path) -> bool:
    source = path.read_text()
    rewritten = rewrite_build_file_contents(source)
    if rewritten == source:
        return False
    path.write_text(rewritten)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add a genrule that renders pregenerated flow/ProtocolVersion.h"
    )
    parser.add_argument(
        "build_files",
        nargs="+",
        help="BUILD or BUILD.bazel files to rewrite",
    )
    args = parser.parse_args()

    for build_file in args.build_files:
        path = Path(build_file)
        if rewrite_build_file(path):
            print(f"Updated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

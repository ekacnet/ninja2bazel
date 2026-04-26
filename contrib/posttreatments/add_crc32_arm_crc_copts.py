#!/usr/bin/env python3
import argparse
import ast
from pathlib import Path
from typing import Optional

TARGET_NAME = "crc32"
PLATFORM_CONDITION = ":platform_linux_arm64"
PLATFORM_COPT = "-march=armv8-a+crc"
DEFAULT_CONDITION = "//conditions:default"


def _string_value(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _make_platform_select() -> ast.Call:
    return ast.Call(
        func=ast.Name(id="select", ctx=ast.Load()),
        args=[
            ast.Dict(
                keys=[
                    ast.Constant(value=PLATFORM_CONDITION),
                    ast.Constant(value=DEFAULT_CONDITION),
                ],
                values=[
                    ast.List(
                        elts=[ast.Constant(value=PLATFORM_COPT)],
                        ctx=ast.Load(),
                    ),
                    ast.List(elts=[], ctx=ast.Load()),
                ],
            )
        ],
        keywords=[],
    )


def _has_platform_select(node: ast.AST) -> bool:
    for subnode in ast.walk(node):
        if not isinstance(subnode, ast.Call):
            continue
        if not isinstance(subnode.func, ast.Name) or subnode.func.id != "select":
            continue
        if len(subnode.args) != 1 or not isinstance(subnode.args[0], ast.Dict):
            continue
        mapping = subnode.args[0]
        for key, value in zip(mapping.keys, mapping.values):
            if _string_value(key) != PLATFORM_CONDITION:
                continue
            if not isinstance(value, ast.List):
                continue
            if any(_string_value(elt) == PLATFORM_COPT for elt in value.elts):
                return True
    return False


def _target_name(call: ast.Call) -> Optional[str]:
    for keyword in call.keywords:
        if keyword.arg == "name":
            return _string_value(keyword.value)
    return None


class Crc32CoptsTransformer(ast.NodeTransformer):
    def __init__(self) -> None:
        self.changed = False

    def visit_Expr(self, node: ast.Expr) -> ast.Expr:
        node = self.generic_visit(node)
        if not isinstance(node.value, ast.Call):
            return node

        call = node.value
        if _target_name(call) != TARGET_NAME:
            return node

        for keyword in call.keywords:
            if keyword.arg != "copts":
                continue
            if _has_platform_select(keyword.value):
                return node
            keyword.value = ast.BinOp(
                left=keyword.value,
                op=ast.Add(),
                right=_make_platform_select(),
            )
            self.changed = True
            return node

        call.keywords.append(
            ast.keyword(
                arg="copts",
                value=ast.BinOp(
                    left=ast.List(elts=[], ctx=ast.Load()),
                    op=ast.Add(),
                    right=_make_platform_select(),
                ),
            )
        )
        self.changed = True
        return node


def rewrite_crc32_copts(source: str) -> str:
    tree = ast.parse(source)
    transformer = Crc32CoptsTransformer()
    tree = transformer.visit(tree)
    if not transformer.changed:
        return source
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def rewrite_build_file(path: Path) -> bool:
    source = path.read_text()
    rewritten = rewrite_crc32_copts(source)
    if rewritten == source:
        return False
    path.write_text(rewritten)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append an ARM CRC select() to the crc32 target copts"
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

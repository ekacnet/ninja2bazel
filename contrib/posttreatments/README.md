# Post-treatments

This directory contains examples of post-treatments that run after `ninja2bazel`
generates a `BUILD.bazel` file.

The example script in this folder parses the generated BUILD file as a Python AST,
finds the target named `crc32`, and rewrites:

```python
copts = ["..."]
```

into:

```python
copts = ["..."] + select({
    ":platform_linux_arm64": ["-march=armv8-a+crc"],
    "//conditions:default": [],
})
```

## Running the example manually

```bash
python3 contrib/posttreatments/add_crc32_arm_crc_copts.py \
    contrib/posttreatments/examples/BUILD.bazel.BUILD.bazel.add_crc
```

## Running it directly from `parser.py`

`parser.py` accepts repeated `--post-treatment` flags. Each script receives the
path to the generated `BUILD.bazel` file and is expected to rewrite it in place.

```bash
python3 parser.py -p "." path/to/build.ninja path/to/src \
    --post-treatment contrib/posttreatments/add_crc32_arm_crc_copts.py
```

There is also a second example that injects a `genrule` producing the output label
`//:pregenerated/flow/include/flow/ProtocolVersion.h` from
`flow/ProtocolVersion.h.cmake` and `flow/ProtocolVersions.cmake`:

```bash
python3 contrib/posttreatments/add_protocol_version_header_genrule.py \
    contrib/posttreatments/examples/protocol_version/BUILD.bazel
```

## Notes

- This example uses `ast.parse()` and `ast.unparse()`, so it normalizes formatting.
- Comments are not preserved by `ast.unparse()`.
- If you want final formatting to be closer to normal Bazel style, run `buildifier`
  after the post-treatment.

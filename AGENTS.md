# Repository Guidelines

## Project Structure & Module Organization
- Core Python modules live at the repo root (e.g., `parser.py`, `ninjabuild.py`, `build.py`, `visitor.py`).
- Shared helpers are in `helpers/` and `helpers.py`.
- Tests live in `test/`, with fixtures under `test/data/`.
- `README.md` documents usage and example workflows.

## Build, Test, and Development Commands
- `python parser.py -p "." path/to/build.ninja path/to/src` runs the main CLI to translate a Ninja build; see `README.md` for full examples and flags.
- `python -m unittest discover -s test` runs the unit test suite using the standard library.
- `pytest` runs the same tests if you prefer pytest (needed for `test/test_integration_build_files.py`).

## Coding Style & Naming Conventions
- Use 4-space indentation and PEP 8 style.
- Follow the line-length limit of 110 characters (see `tox.ini`).
- Prefer `snake_case` for functions/variables and `CamelCase` for classes.
- Test files follow `test_*.py` naming and use `unittest.TestCase`.

## Testing Guidelines
- Add tests for new parsing behaviors and edge cases in `test/`.
- Keep tests deterministic and local; avoid network or system-specific dependencies.
- When adding fixtures, place them under `test/data/` with descriptive names.

## Commit & Pull Request Guidelines
- Commit messages in this repo use short, imperative sentences without prefixes (e.g., "Add documentation on generated stuff").
- Keep commits focused on one change set.
- PRs should include a clear summary, testing notes (commands run), and links to relevant issues when applicable.

## Security & Configuration Tips
- The tool reads local build files and source trees; avoid committing or referencing sensitive paths in fixtures or examples.
- Prefer relative paths in docs and tests so examples work across machines.

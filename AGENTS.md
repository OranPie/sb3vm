# Repository Guidelines

## Project Structure & Module Organization
`sb3vm/` contains the package code. Use `sb3vm/io/` for `.sb3` archive load/save logic, `sb3vm/model/` for project data structures, `sb3vm/parse/` for script extraction and AST nodes, and `sb3vm/vm/` for runtime state, expression evaluation, and execution. The CLI entrypoint lives in `sb3vm/cli.py`. Put regression tests in `tests/`, following the existing split such as `test_roundtrip.py` and `test_vm.py`. Sample assets belong in `examples/`; `examples/demo.sb3` is the current fixture project.

## Build, Test, and Development Commands
Use the repository-local interpreter or `uv`; avoid relying on globally installed `pytest` plugins.

- `uv sync`: create or refresh the local environment from `pyproject.toml` and `uv.lock`.
- `.venv/bin/python -m sb3vm.cli inspect examples/demo.sb3`: inspect a sample Scratch project.
- `.venv/bin/python -m sb3vm.cli run examples/demo.sb3 --seconds 1`: execute the VM headlessly for a fixed duration.
- `.venv/bin/python -m pytest tests`: run the test suite from the local environment.
- `.venv/bin/python make_demo.py`: regenerate the demo archive if you change the example generator.

## Coding Style & Naming Conventions
Target Python 3.11+ and follow the existing style: 4-space indentation, `snake_case` for functions/modules, `PascalCase` for classes, and explicit type hints on public APIs. Keep modules focused by responsibility. Prefer small pure helpers in `io/`, `parse/`, and `vm/` instead of cross-cutting utility files. No formatter or linter is configured in this snapshot, so match the surrounding code closely and keep imports/order tidy.

## Testing Guidelines
Tests use `pytest` with `pythonpath = ["."]` and quiet output enabled in `pyproject.toml`. Name files `test_*.py` and functions `test_*`. Cover both happy paths and data-preservation edge cases, especially for archive roundtrips, unsupported opcodes, waits, broadcasts, and list/variable state updates. Reuse `tests/test_helpers.py::write_sb3` to build minimal `.sb3` fixtures instead of checking binary files into the repo.

## Commit & Pull Request Guidelines
This checkout does not include `.git`, so local history is unavailable. Use short imperative commit subjects, preferably Conventional Commit style such as `feat: add broadcast wait handling` or `fix: preserve project.json fields on resave`. PRs should describe behavior changes, list test coverage, and include CLI output snippets when user-visible VM behavior changes.

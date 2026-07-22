# Contributing

Thank you for improving Media Batch Converter. Keep changes focused, testable, and proportionate to this small desktop project.

## Before opening an issue

- Search existing issues.
- Use the bug or feature template.
- Do not attach private media; create a minimal synthetic sample when reproduction requires a file.
- Remove usernames and local paths from logs and screenshots.

## Development

1. Fork and clone the repository.
2. Create a focused branch from `main`.
3. Create a Python 3.12 virtual environment.
4. Install `requirements-dev.txt`.
5. Make the change and add regression tests.
6. Run:

```powershell
python -m ruff format .
python -m ruff check .
python -m unittest discover -s tests -q
```

For packaging changes, also run `build_windows.bat` and smoke-test the resulting executable.

## Pull requests

Explain the problem and the chosen solution, link related issues, list tests, and include privacy-safe screenshots only when UI behavior changes. Keep unrelated refactors separate. Use clear Conventional Commit-style subjects where practical.

By contributing, you agree that your contribution is licensed under the repository's MIT License.

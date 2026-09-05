#!/usr/bin/env python3
"""Resolve the internal JSON-encoded path input without evaluating shell text."""

import json
import os
import re
import sys
import unicodedata
from pathlib import Path


def resolve_module(source_root: str, value: str) -> tuple[Path, str]:
    if not isinstance(value, str) or not value:
        raise ValueError("path must be a non-empty repository-relative string")
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        raise ValueError("absolute paths are not allowed")
    if "\\" in value or any(unicodedata.category(c) in {"Cc", "Cs", "Zl", "Zp"} for c in value):
        raise ValueError("backslashes and control characters (including NUL/CR/LF) are not allowed")
    if ".." in value.split("/"):
        raise ValueError("parent (..) path components are not allowed")

    root = Path(source_root).resolve(strict=True)
    module = (root / value).resolve(strict=True)
    if not module.is_dir():
        raise ValueError("path must name an existing directory")
    try:
        relative = module.relative_to(root)
    except ValueError as error:
        raise ValueError("resolved path is outside the head checkout (symlink escape)") from error
    prefix = "" if module == root else relative.as_posix()
    if "\\" in prefix or any(unicodedata.category(c) in {"Cc", "Cs", "Zl", "Zp"} for c in str(module)):
        raise ValueError("resolved path contains backslashes or control characters")
    if not any((module / name).is_file() for name in ("go.mod", "go.work")):
        raise ValueError("selected directory must contain go.mod or go.work")
    return module, prefix


def main() -> int:
    try:
        value = json.loads(os.environ["ORDO_PATH_JSON"])
        module, prefix = resolve_module(os.environ["SOURCE_ROOT"], value)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"module_root={module}\nsource_prefix={prefix}\n")
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        print(f"Ordo: invalid path: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

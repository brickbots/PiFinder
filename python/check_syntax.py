#!/usr/bin/env python3
"""
Syntax-check one or more Python source files using the standard ast module.

Usage:
    python check_syntax.py file1.py [file2.py ...]

Exit code:
    0  all files parse without error
    1  one or more files have syntax errors
"""

import ast
import sys
from pathlib import Path


def check_file(path: Path) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR {path}: cannot read — {exc}")
        return False
    try:
        ast.parse(source, filename=str(path))
        print(f"OK: {path}")
        return True
    except SyntaxError as exc:
        print(f"SYNTAX ERROR {path}:{exc.lineno}: {exc.msg}")
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} file1.py [file2.py ...]")
        return 1
    results = [check_file(Path(p)) for p in sys.argv[1:]]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

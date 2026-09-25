#!/usr/bin/env python3
"""Convert ruby annotations from 漢字(かな) style to {漢字|かな} style.

Usage:
  python ruby_to_standard.py input.txt
  python ruby_to_standard.py input.txt output.txt
  python ruby_to_standard.py input.txt --inplace
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

# Match kanji base text followed by reading in parentheses.
# Example: 聴(き) -> {聴|き}
RUBY_PATTERN = re.compile(r"([一-龯々〆ヵヶ]+)\(([^()]+)\)")


def convert_line(line: str) -> tuple[str, int]:
    """Convert one line and return (converted_line, replacement_count)."""

    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        base = match.group(1)
        reading = match.group(2)
        return f"{{{base}|{reading}}}"

    return RUBY_PATTERN.sub(repl, line), count


def convert_text(text: str) -> tuple[str, int]:
    total = 0
    out_lines = []
    for line in text.splitlines(keepends=True):
        converted, n = convert_line(line)
        total += n
        out_lines.append(converted)
    return "".join(out_lines), total


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert ruby from 漢字(かな) to {漢字|かな}."
    )
    parser.add_argument("input", help="Input text file path")
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Output file path (default: <input_stem>_std.txt)",
    )
    parser.add_argument(
        "--inplace",
        action="store_true",
        help="Overwrite input file directly",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    if args.inplace:
        output_path = input_path
    else:
        output_path = (
            Path(args.output)
            if args.output
            else input_path.with_name(f"{input_path.stem}_std{input_path.suffix or '.txt'}")
        )

    text = input_path.read_text(encoding="utf-8")
    converted, total = convert_text(text)
    output_path.write_text(converted, encoding="utf-8")

    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print(f"Replacements: {total}")


if __name__ == "__main__":
    main()

"""Print one targeted section from Elara project context files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
STEP_RE = re.compile(r"^Step\s+(\d+)\s*:", re.IGNORECASE)


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def list_headings(path: Path) -> int:
    for number, line in enumerate(read_lines(path), start=1):
        match = HEADING_RE.match(line)
        if match:
            print(f"{number}: {match.group(1)} {match.group(2)}")
    return 0


def print_heading(path: Path, query: str) -> int:
    lines = read_lines(path)
    needle = query.casefold()
    matches: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match and needle in match.group(2).casefold():
            matches.append((index, len(match.group(1)), match.group(2)))

    if not matches:
        raise SystemExit(f"No heading contains: {query}")
    if len(matches) > 1:
        choices = "\n".join(f"- {title}" for _, _, title in matches)
        raise SystemExit(f"Ambiguous heading query; refine it:\n{choices}")

    start, level, _ = matches[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = HEADING_RE.match(lines[index])
        if match and len(match.group(1)) <= level:
            end = index
            break
    print("\n".join(lines[start:end]).rstrip())
    return 0


def print_step(path: Path, step: int) -> int:
    lines = read_lines(path)
    starts = [
        (index, int(match.group(1)))
        for index, line in enumerate(lines)
        if (match := STEP_RE.match(line))
    ]
    selected = [index for index, number in starts if number == step]
    if not selected:
        raise SystemExit(f"Step {step} was not found in {path}")
    start = selected[0]
    end = next((index for index, _ in starts if index > start), len(lines))
    print("\n".join(lines[start:end]).rstrip())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    headings = subparsers.add_parser("headings", help="list Markdown headings")
    headings.add_argument("path", type=Path)

    heading = subparsers.add_parser("heading", help="print one Markdown section")
    heading.add_argument("path", type=Path)
    heading.add_argument("query")

    step = subparsers.add_parser("step", help="print one numbered project prompt")
    step.add_argument("path", type=Path)
    step.add_argument("number", type=int, choices=range(1, 27))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "headings":
        return list_headings(args.path)
    if args.command == "heading":
        return print_heading(args.path, args.query)
    return print_step(args.path, args.number)


if __name__ == "__main__":
    raise SystemExit(main())

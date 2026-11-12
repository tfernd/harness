#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Set
from pathlib import Path
from typing import NamedTuple

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
SKILL_KEYS = frozenset({"name", "description"})
AGENT_KEYS = frozenset({"name", "description", "tools", "model", "skills"})
SCANNED_FOLDERS = ("skills", "agents", "templates", "hooks")
HARNESS_REF = re.compile(r"harness:([a-z][a-z0-9-]*)")
REFERENCE_FILE = re.compile(r"references/([\w.-]+\.[\w]+)")
KEY_LINE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")
ITEM_LINE = re.compile(r"^\s+-\s+(.*?)\s*$")


class Frontmatter(NamedTuple):

    fields: dict[str, str | list[str]]
    body: list[str]


def split_frontmatter(text: str, /) -> Frontmatter | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None
    fields: dict[str, str | list[str]] = {}
    key = ""
    for line in lines[1:end]:
        if match := KEY_LINE.match(line):
            key = match.group(1)
            fields[key] = match.group(2).strip()
        elif (item := ITEM_LINE.match(line)) and key:
            current = fields[key]
            fields[key] = [*current, item.group(1)] if isinstance(current, list) else [item.group(1)]
    return Frontmatter(fields, lines[end + 1 :])


def read_documents(root: Path, kind: str, filename: str, /) -> list[Path]:
    folder = root / kind
    if not folder.is_dir():
        return []
    if kind == "skills":
        return sorted(folder.glob(f"*/{filename}"))
    return sorted(folder.glob("*.md"))


def check_frontmatter(rel: str, fields: dict[str, str | list[str]], allowed: Set[str], /) -> list[str]:
    problems = [f"{rel}: frontmatter key not allowed: {key}" for key in fields if key not in allowed]
    problems += [f"{rel}: frontmatter key missing: {key}" for key in sorted(allowed) if key not in fields]
    return problems


def check_skill(root: Path, path: Path, /) -> list[str]:
    rel = path.relative_to(root).as_posix()
    parsed = split_frontmatter(path.read_text())
    if parsed is None:
        return [f"{rel}: no frontmatter"]
    fields, body = parsed
    problems = check_frontmatter(rel, fields, SKILL_KEYS)
    if fields.get("name") != path.parent.name:
        problems.append(f"{rel}: name {fields.get('name')!r} differs from folder {path.parent.name!r}")
    for name in dict.fromkeys(REFERENCE_FILE.findall("\n".join(body))):
        if not (path.parent / "references" / name).is_file():
            problems.append(f"{rel}: references/{name} does not exist")
    return problems


def check_agent(root: Path, path: Path, skill_names: Set[str], /) -> list[str]:
    rel = path.relative_to(root).as_posix()
    parsed = split_frontmatter(path.read_text())
    if parsed is None:
        return [f"{rel}: no frontmatter"]
    fields, _ = parsed
    problems = check_frontmatter(rel, fields, AGENT_KEYS)
    listed = fields.get("skills", [])
    for name in listed if isinstance(listed, list) else [listed]:
        if name and name not in skill_names:
            problems.append(f"{rel}: lists skill {name!r} that does not exist")
    return problems


def check_harness_refs(root: Path, known: Set[str], /) -> list[str]:
    problems = []
    for folder in SCANNED_FOLDERS:
        base = root / folder
        for path in sorted(base.rglob("*")) if base.is_dir() else []:
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                for name in HARNESS_REF.findall(line):
                    if name not in known:
                        problems.append(f"{path.relative_to(root).as_posix()}:{number}: harness:{name} names no skill or agent")
    return problems


def check_tree(root: Path, /) -> list[str]:
    skills = read_documents(root, "skills", "SKILL.md")
    agents = read_documents(root, "agents", "")
    skill_names = {path.parent.name for path in skills}
    known = skill_names | {path.stem for path in agents}
    problems = []
    for path in skills:
        problems += check_skill(root, path)
    for path in agents:
        problems += check_agent(root, path, skill_names)
    return problems + check_harness_refs(root, known)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when a skill or an agent leaves the form AGENTS.md demands.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="tree to check")
    root = parser.parse_args().root.resolve()
    problems = check_tree(root)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

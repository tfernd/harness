#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""Fail when a tracked or trackable file names a person, a machine or a private project.

Checks every file git would track for absolute home paths, email addresses and
the words of a private list. The list is read from $HARNESS_PRIVATE_WORDS, else
~/.config/harness/private-words when it exists. It is never in the repo and its
path is never printed.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDERS = {"user", "you", "name", "username", "me", "yourname", "your-name", "example", "<user>", "$user"}
HOME = re.compile(r"(?:/ho" r"me/|/Us" r"ers/|[A-Za-z]:\\Us" r"ers\\)([^/\\\s\"'`)]+)")
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
EMAIL_OK = {"anthropic.com", "users.noreply.github.com"}
# The one place a handle may appear: the repo's own install path.
REPO_PATH = "tfernd/harness"


def private_words() -> list[str]:
    env = os.environ.get("HARNESS_PRIVATE_WORDS")
    path = Path(env) if env else Path.home() / ".config" / "harness" / "private-words"
    if not path.is_file():
        print(f"note: no private word list at {path.name}, so private words were not checked", file=sys.stderr)
        return []
    lines = (w.strip().lower() for w in path.read_text().splitlines())
    return [w for w in lines if w and not w.startswith("#")]


def files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return sorted(set(out.splitlines()))


def main() -> int:
    words = private_words()
    bad = 0
    for rel in files():
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            low = line.lower().replace(REPO_PATH, "")
            kinds = []
            for m in HOME.finditer(line):
                if m.group(1).lower() not in PLACEHOLDERS:
                    kinds.append("absolute home path")
            for m in EMAIL.finditer(line):
                if m.group(1).lower() not in EMAIL_OK:
                    kinds.append("email address")
            if any(w in low for w in words):
                kinds.append("word from the private list")
            for kind in dict.fromkeys(kinds):
                print(f"{rel}:{n}: {kind}")
                bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

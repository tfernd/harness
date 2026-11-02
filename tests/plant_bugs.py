#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""Plants random bugs in copies of the hooks and scores how many the cases catch.

Why: `tests/mutants.py` holds the bugs someone thought of, so it cannot show what nobody thought of. This one changes a token
at a random site (a comparison, a boolean, a branch) and runs the cases on the copy. A survivor is either a rule no case guards
or a change that alters nothing; read it to tell which. The same seed on the same code plants the same bugs; after a code change the sites move, so two scores compare only roughly. Nothing
outside `scratch/hook-mutants` changes. A row prints per bug as it finishes; the last lines hold the score per hook. Always
exits 0, since a survivor is a lead, not a failure.

uv run python tests/plant_bugs.py [--count N] [--seed N] [--only HOOK] [--jobs N]
"""

from __future__ import annotations

import argparse
import collections
import io
import random
import shutil
import subprocess
import sys
import tokenize
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import NamedTuple

from mutants import HOOKS, RUN_CASES, TIMEOUT, WORK

# What each token becomes. Only code tokens are read, so a string, a comment or a docstring is never changed.
SWAPS = {
    "==": "!=",
    "!=": "==",
    "<": "<=",
    "<=": "<",
    ">": ">=",
    ">=": ">",
    "and": "or",
    "or": "and",
    "True": "False",
    "False": "True",
    "not": "",
    "is": "is not",
    "in": "not in",
    "continue": "pass",
    "break": "pass",
    "+": "-",
    "startswith": "endswith",
    "endswith": "startswith",
    "any": "all",
    "all": "any",
}
# A hand-run tool whose one case reads its summary alone.
SKIPPED = {"replay.py"}


class Site(NamedTuple):
    """One token that can change: its hook, its place and what it becomes."""

    script: str
    line: int
    column: int
    old: str
    new: str


def get_sites(script: str, /) -> list[Site]:
    """Every changeable code token of one hook, its import and `__main__` lines left out."""

    text = (HOOKS / script).read_text()
    sites = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        is_code = token.type in (tokenize.OP, tokenize.NAME)
        source = token.line.lstrip()
        is_plumbing = source.startswith(("import ", "from ", "if __name__"))
        if is_code and token.string in SWAPS and not is_plumbing:
            sites.append(Site(script, token.start[0], token.start[1], token.string, SWAPS[token.string]))

    return sites


def apply_site(site: Site, text: str, /) -> str:
    """The hook's text with the one token changed."""

    lines = text.split("\n")
    line = lines[site.line - 1]
    lines[site.line - 1] = line[: site.column] + site.new + line[site.column + len(site.old) :]

    return "\n".join(lines)


def run_site(index: int, site: Site, /) -> tuple[Site, str, str]:
    """Plants one bug in a copy and runs the cases on it; returns the site, killed or survived, and the changed line."""

    folder = WORK / f"planted-{index}"
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree(HOOKS, folder, ignore=shutil.ignore_patterns("__pycache__"))
    path = folder / site.script
    text = apply_site(site, path.read_text())
    path.write_text(text)
    changed = text.split("\n")[site.line - 1].strip()
    try:
        run = subprocess.run(["uv", "run", "python", str(RUN_CASES), "--hooks", str(folder)], capture_output=True, text=True, timeout=TIMEOUT)
        verdict = "survived" if run.returncode == 0 else "killed"
    except subprocess.TimeoutExpired:
        verdict = "killed"
    shutil.rmtree(folder)

    return site, verdict, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=200, help="how many bugs to plant")
    parser.add_argument("--seed", type=int, default=1, help="the same seed plants the same bugs")
    parser.add_argument("--only", default="", help="plant only in the hooks whose name holds this text")
    parser.add_argument("--jobs", type=int, default=6, help="bugs at once; each runs its cases on eight threads")
    arguments = parser.parse_args()
    scripts = sorted(path.name for path in HOOKS.glob("*.py") if path.name not in SKIPPED and arguments.only in path.name)
    sites = [site for script in scripts for site in get_sites(script)]
    chosen = random.Random(arguments.seed).sample(sites, min(arguments.count, len(sites)))
    print(f"{len(sites)} sites in {len(scripts)} hooks; planting {len(chosen)}, seed {arguments.seed}", flush=True)
    totals: collections.Counter[str] = collections.Counter()
    survivors: collections.Counter[str] = collections.Counter()
    with ThreadPoolExecutor(arguments.jobs) as pool:
        futures = [pool.submit(run_site, index, site) for index, site in enumerate(chosen)]
        for future in as_completed(futures):
            site, verdict, changed = future.result()
            totals[site.script] += 1
            survivors[site.script] += verdict == "survived"
            if verdict == "survived":
                print(f"SURVIVED {site.script}:{site.line} {site.old!r} -> {site.new!r}: {changed[:150]}", flush=True)
    for script, total in sorted(totals.items()):
        print(f"{script:16} {total - survivors[script]}/{total} caught")
    caught = sum(totals.values()) - sum(survivors.values())
    print(f"score {caught}/{sum(totals.values())} = {100 * caught / max(1, sum(totals.values())):.0f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())

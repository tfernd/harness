#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""Run the hook cases: what the guard refuses, when a report goes back, when the Stop hook holds a turn, what the delegate
and brief rules refuse, and what the context hook says.

Why: a hook is code that blocks every agent when it is wrong, and a hook that is too loose lets the rule it enforces rot
unseen. Each case feeds a hook the JSON the harness sends, in a temporary project and data folder, and checks whether it
blocked. `CLAUDE_PROJECT_DIR` is cleared, and set only by the cases that ask. A line per case prints; the exit code is 1
when any case fails. Stdlib only.

uv run python tests/run_cases.py [--only SUBSTRING] [--hooks FOLDER]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
HOOK_TIMEOUT = 10
JOBS = 8
# The temporary projects: outside /tmp, which a strict project refuses, and outside this repo, whose own `.harness.json`
# a case with no config would find.
WORK = Path.home() / ".cache" / "harness-cases"
SESSION = "case-session"
# Stands for the case's temporary folder in an event or a transcript line.
ROOT = "@ROOT@"
LOCK_MESSAGE = "this project's Python runs under its queue"
# A strict project, shaped like the one this plugin first served.
STRICT = {
    "guard": {
        "scratch": "scratch",
        "no_tmp": True,
        "deny_packages": True,
        "lock": {
            "commands": ["bin/queue", "bin/queue-lock"],
            "free_env": "NO_QUEUE=",
            "free_scripts": ["bin/api_index.py"],
            "free_prefixes": ["tools.", "tools/"],
            "message": LOCK_MESSAGE,
        },
    },
}
BUSY_CALLS = ["Agent", "Edit", "Edit"]
FULL_STATUS = "\n".join(f"## {heading}\nnothing" for heading in ("Verdict", "Done", "Needs you", "Next", "Lessons"))
PROGRESS = "Progress: two files are written, the third agent is still running."
CARD = (
    "| Score | Value | Why |\n| --- | --- | --- |\n| Task | 5/5 | done |\n| Brief | 4/5 | clear |\n| Ease | 5 | easy |\n\n"
    "**What would have helped:** nothing\n\n**How I would do it again:** the same"
)
REPORT_SECTIONS = (
    ("Answer", "Done."),
    ("Work", "- one file changed"),
    ("NOT CHECKED", "none"),
    ("OUTSIDE", "none"),
    ("DECIDE", "none"),
    ("PROBLEMS MET", "no problem met: the gates ran clean"),
    ("COMPLIANCE", "Gates: the style gate exit 0"),
    ("LEARNED", "- a fact"),
    ("REPORT CARD", CARD),
    ("FEEDBACK FOR THE ORCHESTRATOR", "none"),
)
SHORT_HEADINGS = ("Answer", "Work", "NOT CHECKED", "PROBLEMS MET", "REPORT CARD")


def make_report(*, skip: str = "", headings: tuple[str, ...] = (), replace: tuple[str, str] = ("", "")) -> str:
    """A report in the skill's form: `skip` leaves a heading out, `headings` keeps only those, `replace` swaps a body."""

    sections = [(heading, replace[1] if heading == replace[0] else body) for heading, body in REPORT_SECTIONS]
    kept = [(heading, body) for heading, body in sections if heading != skip and (not headings or heading in headings)]

    return "\n".join(f"## {heading}\n{body}" for heading, body in kept)


class Case(NamedTuple):
    """One hook run in a temporary project.

    `blocks` says whether the hook must block; `text` must be in what it prints, `lacks` must not. `files` are written
    first, under the project (or the data folder when the name starts with `data/`); `wrote` is a file and a text it must
    then hold, `not_wrote` a file and a text it must not. `config` is `.harness.json`, None for no file. `cwd` is the
    event's folder and `project_dir` the value of `CLAUDE_PROJECT_DIR`, each relative to the case's temporary folder and
    created if missing; `links` are symlinks made there, as (name, target). `before` are hook runs that go first, as
    (script, event), whose result does not count. ROOT in an event or a transcript stands for the temporary folder.
    """

    name: str
    script: tuple[str, ...]
    event: dict  # keys are data
    blocks: bool
    text: str = ""
    config: dict | None = None  # keys are data
    files: tuple[tuple[str, str], ...] = ()
    wrote: tuple[str, str] | None = None
    not_wrote: tuple[str, str] | None = None
    transcript: tuple[dict, ...] = ()
    is_exit_one: bool = False
    lacks: str = ""
    cwd: str = "project"
    project_dir: str = ""
    links: tuple[tuple[str, str], ...] = ()
    before: tuple[tuple[tuple[str, ...], dict], ...] = ()
    shell: str = "/usr/bin/zsh"


# ===========================================================================
# The guard
# ===========================================================================


def bash(name: str, command: str, blocks: bool, text: str = "", /, *, config: dict | None = STRICT, **options: object) -> Case:  # keys are data
    event = {"tool_name": "Bash", "tool_input": {"command": command}}

    return Case(name, ("guard.py",), event, blocks, text, config, **options)


def write_call(name: str, path: str, blocks: bool, text: str = "", /) -> Case:
    event = {"tool_name": "Write", "tool_input": {"file_path": path}}

    return Case(name, ("guard.py",), event, blocks, text, STRICT)


# The real uv cache, kept because each case sets HOME to its own folder.
UV_CACHE = os.environ.get("UV_CACHE_DIR") or str(Path.home() / ".cache" / "uv")
HEREDOC = "python3 - <<'EOF'\nfrom pathlib import Path\n{call}\nEOF"
# The form Claude Code writes a commit message in.
COMMIT = "git commit -m \"$(cat <<'EOF'\n{body}\nEOF\n)\""
DELETE = "nothing is deleted"
HISTORY = "owner's to run"
GLOB = "unquoted glob"
REPO = "project files change"
GUARD_CASES = [
    bash("a bare uv run does not crash", "uv run", False),
    bash("a bare tar does not crash", "tar", False),
    bash("a quote in a quoted parameter opens nothing", """echo "${X:-it's}"; uv pip install y""", True),
    bash("a command after an ansi quote is still read", "echo $'a'; uv pip install y", True),
    bash("a command in a counted for loop is still read", "for ((i=0;i<1;i++)); do uv pip install y; done", True),
    bash("a bare bash -c does not crash", "bash -c", False),
    bash("a script named like a command is no command string", 'bash -x "pip install y"', False),
    bash("the words of a plain find run nothing", "find . pip install y", False),
    Case("a notebook under the temporary folder is refused", ("guard.py",), {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/tmp/n.ipynb"}}, True, config=STRICT),
    bash("an escaped letter stays in its word", r"p\ip install x", True),
    bash("a sleep under find is no polling", r"find . -exec sleep 1 \;", False),
    bash("a sleep under an unended find is no polling", "find . -exec sleep 1", False),
    bash("git with options alone passes", "git --version", False),
    bash("uv with options alone passes", "uv --version", False),
    bash("an export of another variable frees nothing", "export FOO=1; uv run python x.py", True, LOCK_MESSAGE),
    bash("a positional parameter stays in a path", "echo a > /$1tmp/y", False),
    bash("a tar made under the temporary folder is refused", "tar -cf /tmp/a.tar b", True),
    bash("a cd in a subshell does not move the next step", "(cd scratch); echo hi > AGENTS.md", True, REPO),
    bash("an open backtick does not crash", "echo `ls", False),
    bash("a command after a parameter is still read", "echo ${X}; uv pip install y", True),
    bash("an open parameter does not crash", "echo ${X", False),
    bash("an in-place edit of a missing file is no write", "sed -i s/a/b/ /tmp/nope.txt", False),
    bash("rm is refused", "rm x", True, "nothing is deleted"),
    bash("git clean is refused", "git clean -fd", True, "nothing is deleted"),
    bash("a plain git push is allowed", "git push -u origin topic", False),
    bash("a failing glob is refused in zsh", "ls *.nothing", True, "matches no file"),
    bash("a failing glob passes when the shell is not zsh", "ls *.nothing", False, shell="/bin/bash"),
    bash("an option glob passes when the shell is not zsh", "grep -rn x --include=*.py .", False, shell="/bin/bash"),
    bash("no shell at all judges no glob", "ls *.nothing", False, shell=""),
    bash("a glob after a step that may write passes", "make && ls out/*.nothing", False),
    bash("a glob after a redirect passes", "echo hi > scratch/t/o.txt; cat scratch/t/o.*", False),
    bash("a glob after find -exec passes", "find . -name x -exec touch q1 \\; ; cat q*", False, config=None),
    bash("a glob after a read still fails", "echo hi; ls *.nothing", True, "matches no file"),
    bash("an option glob after a step that may write still fails", "make && grep -rn x --include=*.py .", True, "matches no file"),
    bash("a glob in bash -c passes", "bash -c 'ls *.nothing'", False),
    bash("an option glob in sh -c passes", "sh -c 'grep -rn x --include=*.py .'", False),
    bash("a glob in zsh -c is refused", "zsh -c 'ls *.nothing'", True, "matches no file"),
    bash("a loop with no sleep passes", "while read line; do echo hi; done", False),
    bash("a sleep in an inner polling loop is refused", "for x in a; do while true; do sleep 1; done; done", True),
    bash("curl writing into the repo is refused", "curl -o AGENTS.md http://x", True),
    bash("curl with no output file passes", "curl http://x", False),
    bash("a copy into the repo is refused", "cp a AGENTS.md", True),
    bash("a venv python without the lock is refused", ".venv/bin/python x.py", True, LOCK_MESSAGE),
    bash("a plain sed passes", "sed -n 1p AGENTS.md", False),
    bash("a sed -i in the repo is refused", "sed -i s/a/b/ AGENTS.md", True),
    bash("an allowed uv command passes", "uv tree", False),
    bash("the free variable named by another command frees nothing", "echo NO_QUEUE=; uv run python x.py", True, LOCK_MESSAGE),
    bash("listing a tar writes nothing", "tar -tf a.tar", False),
    bash("cd past an option still knows its folder", "cd -P scratch/t && echo x > a.txt", False),
    bash("a <<- heredoc body is no command", "cat <<-EOF\nrm x\nEOF", False),
    bash("a forced git push is refused", "git push --force origin topic", True, "owner's to run"),
    bash("a +ref git push is refused", "git push origin +topic", True, "owner's to run"),
    bash("a delete git push is refused", "git push origin --delete topic", True, "owner's to run"),
    bash("git reset --hard is refused", "git reset --hard HEAD~1", True, "owner's to run"),
    bash("uv sync is refused", "uv sync", True, "owner's to run"),
    bash("uv run python without the lock is refused", "uv run python x.py", True, LOCK_MESSAGE),
    bash("uv run python under queue is allowed", "bin/queue -- uv run python x.py", False),
    bash("uv run python with the free variable is allowed", "NO_QUEUE= uv run python x.py", False),
    bash("a free script needs no lock", "uv run python bin/api_index.py", False),
    bash("a module under a free prefix needs no lock", "uv run python -m tools.gates.style", False),
    bash("a script under a free prefix needs no lock", "uv run python tools/api_index.py", False),
    bash("a module outside every free prefix is refused", "uv run python -m toolsx.run", True, LOCK_MESSAGE),
    bash("an unquoted glob is refused", "ls *.py", True, "unquoted glob"),
    bash("a quoted glob is allowed", "ls '*.py'", False),
    bash("an unquoted glob in an option is refused", "grep --include=*.py x .", True, "unquoted glob"),
    bash("a glob that matches a file is allowed", "wc -l *.py", False, files=(("a.py", ""),)),
    bash("a loop over a glob that matches is allowed", "for name in *.py; do echo $name; done", False, files=(("a.py", ""),)),
    bash("a glob that matches beside one that does not is refused", "ls *.py *.nothing", True, GLOB, files=(("a.py", ""),)),
    bash("a glob is matched from the folder a cd reaches", "cd sub && ls *.py", True, GLOB, files=(("a.py", ""), ("sub/b.txt", ""))),
    bash("a glob matches in the folder a cd reaches", "cd sub && ls *.py", False, files=(("sub/a.py", ""),)),
    bash("a ** glob reaches every depth", "ls **/a.py", False, files=(("sub/deep/a.py", ""),)),
    bash("a glob from an unknown folder is not judged", "cd $x && ls *.nothing", False),
    bash("an absolute glob from an unknown folder is judged", "cd $x && ls /nothing-here/*.py", True, GLOB),
    bash("a glob behind a variable is not judged", "ls $x/*.nothing", False),
    bash("a glob with braces is not judged", "ls {a,b}/*.nothing", False),
    bash("a glob in an option from an unknown folder is refused", "cd $x && grep --include=*.py x .", True, GLOB),
    bash("find -name with a glob that matches is refused", "find . -name *.py", True, GLOB, files=(("a.py", ""),)),
    bash("rg -g with a glob that matches is refused", "rg -g *.py x", True, GLOB, files=(("a.py", ""),)),
    bash("grep --include with a glob that matches is refused", "grep --include *.py x .", True, GLOB, files=(("a.py", ""),)),
    bash("a matching glob after another command's -name is allowed", "ls -name *.py", False, files=(("a.py", ""),)),
    bash("$? is no glob", "echo $?", False),
    bash("a redirect into /tmp is refused", "echo hi > /tmp/x", True, "never under /tmp"),
    bash("a redirect over a project file is refused", "echo hi > AGENTS.md", True, "project files change"),
    bash("a redirect into scratch is allowed", "echo hi > scratch/t/x.txt", False),
    bash("sed -i on a project file is refused", "sed -i s/a/b/ AGENTS.md", True, "project files change"),
    bash("a sleep in a while loop is refused", "while true; do sleep 1; done", True, "polls"),
    bash("a sleep in a for loop is allowed", "for i in 1 2; do sleep 1; done", False),
    bash("python -c is not read as a shell", "python3 -c 'print(2 > 1)'", False),
    bash("a python heredoc is not read as a shell", HEREDOC.format(call="print(2 > 1)"), False),
    bash("a heredoc body is no command", "cat <<'EOF'\nrm x\nEOF", False),
    bash("a command after a heredoc is judged", "cat <<'EOF'\nx\nEOF\necho hi > AGENTS.md", True, "project files change"),
    bash("a here-string word is no argument", "cat <<< a*b", False),
    bash("a soft git reset is allowed", "git reset --soft HEAD~1", False),
    bash("a plain git reset is allowed", "git reset HEAD~1", False),
    bash("git rm is allowed", "git rm -q scratch/x", False),
    bash("the venv's python without the lock is refused", ".venv/bin/python x.py", True, LOCK_MESSAGE),
    bash("uv run python inside bash -c is refused", "bash -c 'uv run python x.py'", True, LOCK_MESSAGE),
    bash("the lock inside bash -c is allowed", "bash -c 'bin/queue -- uv run python x.py'", False),
    bash("uv run python after env VAR=1 is refused", "env FOO=1 uv run python x.py", True, LOCK_MESSAGE),
    bash("a project write inside bash -c is refused", "bash -c 'echo hi > AGENTS.md'", True, "project files change"),
    write_call("a Write under /tmp is refused", "/tmp/x.txt", True, "never under /tmp"),
    write_call("a Write of a project file is allowed", "AGENTS.md", False),
    bash("rm is refused with no project", "rm x", True, "nothing is deleted", config=None),
    bash("a forced push is refused with no project", "git push -f", True, "owner's to run", config=None),
    bash("a glob is refused with no project", "ls *.py", True, "unquoted glob", config=None),
    bash("a sleep poll is refused with no project", "until false; do sleep 1; done", True, "polls", config=None),
    bash("a repo redirect is allowed with no project", "echo hi > AGENTS.md", False, config=None),
    bash("a /tmp redirect is allowed with no project", "echo hi > /tmp/x", False, config=None),
    bash("uv sync is allowed with no project", "uv sync", False, config=None),
    bash("pip is allowed with no project", "pip install x", False, config=None),
    bash("bare uv run python is allowed with no project", "uv run python x.py", False, config=None),
    # Holes: each of these runs something a rule refuses.
    *(bash(f"refused: {command!r}", command, True, HISTORY, config=None) for command in (
        "git push -fu origin main",
        "git push -uf origin main",
        "sh -ec 'git push --force'",
    )),
    *(bash(f"refused: {command!r}", command, True, DELETE, config=None) for command in (
        "bash -lc 'rm x'",
        "bash -c 'rm x'",
        "zsh -ic 'rm x'",
        "bash -o pipefail -c 'rm x'",
        "find . -name x -exec rm {} +",
        "find . -name x -execdir rm {} \\;",
        "find . -name x -ok rm {} \\;",
        "find . -exec sh -c 'rm x' \\;",
        "sudo -n rm x",
        "sudo -u root rm x",
        "sudo --user root rm x",
        "sudo rm x",
        "diff <(rm x) y",
        "while read l; do echo; done < <(rm x)",
        "echo a > >(rm x)",
        "exec 3>&-; rm x",
        "git --git-dir .git clean -fd",
        "git --work-tree . clean -fd",
        "git -C . clean -fd",
        'eval "rm x"',
        "eval rm x",
        "echo $(( $(rm x) + 1 ))",
        "echo $((rm x) && (echo y))",
        "echo ${a:-$(rm x)}",
        '[[ -n "$(rm x)" ]] && echo y',
        "[[ -n $(rm x) ]] && echo y",
        "cat <<EOF\n$(rm x)\nEOF",
        "cat <<EOF\n`rm x`\nEOF",
        "echo `rm x`",
        "echo $(case a in a) rm x;; esac)",
        COMMIT.format(body="sad :(") + " && rm -rf x",
        COMMIT.format(body="glad") + " && rm -rf x",
    )),
    bash("a sleep in a [[ loop is refused", "while [[ -z $x ]]; do sleep 1; done", True, "polls", config=None),
    bash("a glob after [[ ]] is judged", "[[ -f x ]] && ls *.py", True, GLOB, config=None),
    bash("a glob after $(( )) is judged", "echo $((1 + 1)) *.py", True, GLOB, config=None),
    bash("strict: python3 -m pip is refused", "python3 -m pip install x", True, HISTORY),
    bash("strict: python -mpip is refused", "python -mpip install x", True, HISTORY),
    bash("strict: uv run pip is refused", "uv run pip install x", True, HISTORY),
    bash("strict: uv run python -m pip is refused", "NO_QUEUE= uv run python -m pip install x", True, HISTORY),
    bash("strict: mv of a project file is refused", "mv AGENTS.md scratch/gone", True, REPO),
    bash("strict: mv inside scratch is allowed", "mv scratch/a scratch/b", False),
    bash("strict: mv of a /tmp file into scratch is allowed", "mv /tmp/a scratch/b", False),
    bash("strict: cp out of the project tree into scratch is allowed", "cp AGENTS.md scratch/copy", False),
    bash("strict: cp -t names its destination", "cp -t . scratch/x", True, REPO),
    bash("strict: cp -t into scratch is allowed", "cp -t scratch AGENTS.md", False),
    # False refusals: none of these runs anything a rule refuses.
    *(bash(f"allowed: {command!r}", command, False, config=None) for command in (
        "echo $((2 * 3))",
        "i=$(( i * 2 ))",
        'echo "$(( 1024 * 1024 ))"',
        '[[ "$f" == *.py || "$f" == *.sh ]] && echo y',
        '[[ "$x" == -* ]] && echo y',
        "echo ${line%% *}",
        'echo "${line%% *}"',
        "echo ${x:-*}",
        "(( i * 2 )) && echo y",
        "for ((i = 0; i < 3; i++)); do echo $i; done",
        "echo $# $? $*",
        "echo $'it\\'s; rm x'",
        "export FLAGS=a*b",
        "echo x # rm y",
        COMMIT.format(body='Fix: 1) match "*.py" files'),
        COMMIT.format(body='Fix: 1) note "a; rm b" text'),
        COMMIT.format(body='Fix (balanced) match "*.py; rm b" files'),
        COMMIT.format(body="it's sad :("),
        "cat <<'EOF'\n$(rm x)\nEOF",
        "cat <<\\EOF\n$(rm x)\nEOF",
        "git reset --soft HEAD~1",
        "git push origin main:main",
    )),
    bash("strict: echo $(( 5 > 3 )) writes nothing", "echo $(( 5 > 3 ))", False),
    bash('strict: [[ "$a" > "$b" ]] writes nothing', '[[ "$a" > "$b" ]] && echo y', False),
    bash("strict: (( a > b )) writes nothing", "(( 5 > 3 )) && echo y", False),
    bash("strict: a pipeline after a cd keeps the folder", "cd scratch && make 2>&1 | tee out.log", False),
    bash("strict: a later command after a pipeline keeps the folder", "cd scratch && echo a | cat && echo hi > ok.txt", False),
    bash("strict: a redirect at a pipeline's end keeps the folder", "cd scratch && git log | head -3 > out.txt", False),
    bash("strict: a cd in a pipeline leaves the folder unknown", "cd scratch | cat; echo hi > ok.txt", True, REPO),
    bash("strict: a cd in the background leaves the folder unknown", "cd scratch & echo hi > ok.txt", True, REPO),
    bash("strict: a cd and its list in the background", "cd scratch && echo a &\necho hi > ok.txt", True, REPO),
    bash("strict: a cd in a substitution leaves the folder", "x=$(cd scratch); echo hi > AGENTS.md", True, REPO),
    bash("strict: a command after a redirect target is no target", "echo a >&2; rm x", True, DELETE),
    bash("strict: a malformed redirect does not swallow the next command", "echo a > ; rm x", True, DELETE),
    bash("strict: a closed descriptor names no file", "echo a >&- b", False),
    bash("strict: a cd after an ended pipeline keeps its folder", "echo a | cat; cd scratch; echo hi > ok.txt", False),
    bash("an argument after a process substitution is no command", "diff <(sort a) rm", False, config=None),
    bash("strict: scratch/ is the scratch folder", "echo hi > scratch/x.txt", False, config={"guard": {"scratch": "scratch/"}}),
    bash("strict: ./scratch is the scratch folder", "echo hi > scratch/x.txt", False, config={"guard": {"scratch": "./scratch"}}),
    bash("strict: scratch/ still guards the rest", "echo hi > AGENTS.md", True, REPO, config={"guard": {"scratch": "scratch/"}}),
    bash("strict: a symlinked cwd is still inside", "echo hi > AGENTS.md", True, REPO, cwd="link", links=(("link", "project"),)),
    bash("strict: a symlinked cwd still reaches scratch", "echo hi > scratch/x.txt", False, cwd="link", links=(("link", "project"),)),
    bash("strict: a symlink in scratch to the project is a project write", "echo hi > scratch/out/AGENTS.md", True, REPO, links=(("project/scratch/out", "project"),)),
    bash("the project variable pins the rules past a cd", "uv sync", True, HISTORY, cwd="elsewhere", project_dir="project"),
    bash("the project variable pins the writes too", "echo hi > ../project/AGENTS.md", True, REPO, cwd="elsewhere", project_dir="project"),
    bash("the project variable wins over a cwd's config", "uv sync", False, cwd="project", project_dir="elsewhere"),
    bash("without the variable the walk goes up from cwd", "uv sync", True, HISTORY, cwd="project/scratch/t"),
    bash("without the variable a cwd outside has no rules", "uv sync", False, cwd="elsewhere"),
    Case(
        "a broken config shows an error and lets the call run",
        ("guard.py",),
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        False,
        "guard failed",
        files=((".harness.json", "{not json"),),
        is_exit_one=True,
    ),
]


# ===========================================================================
# The report gate
# ===========================================================================


def stop_event(report: str, /, *, agent_type: str = "harness:worker", agent_id: str = "a1") -> dict:  # keys are data
    return {"agent_type": agent_type, "agent_id": agent_id, "last_assistant_message": report, "session_id": SESSION}


def transcript_event(report: str, /) -> dict:  # keys are data
    """An event of a sub-agent with its own transcript; its report may lie in the transcript."""

    return {**stop_event(report), "agent_transcript_path": "transcript.jsonl"}


def assistant(*blocks: dict) -> dict:  # keys are data
    return {"type": "assistant", "message": {"content": list(blocks)}}


def edit(tool_id: str, path: str, /) -> dict:  # keys are data
    """An Edit call on a path relative to the project, in a transcript line."""

    return assistant({"type": "tool_use", "id": tool_id, "name": "Edit", "input": {"file_path": path}})


def work_report(work: str, /) -> str:
    """A complete report with a Work of this text and no exit code."""

    return make_report(replace=("Work", work)).replace("Gates: the style gate exit 0", "no gate applied")


def gate(name: str, event: dict, blocks: bool, text: str = "", /, **options: object) -> Case:  # keys are data
    options.setdefault("config", {})

    return Case(name, ("report_gate.py",), event, blocks, text, **options)


INBOX_NAME = "harness-feedback/inbox.md"
AUTO = "[auto] "
NUMBERED = "\n".join(f"line {word}" for word in ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"))


def bash_call(tool_id: str, /) -> dict:  # keys are data
    return assistant({"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": "true"}})


def bash_failed(tool_id: str, code: int, /) -> dict:  # keys are data
    """The error result of a Bash call, as the transcript records a nonzero exit."""

    block = {"type": "tool_result", "tool_use_id": tool_id, "is_error": True, "content": f"Exit code {code}\noutput"}

    return {"type": "user", "message": {"content": [block]}}
HANDLED_NAME = "harness-feedback/handled.md"
CLEAN_REPORT = work_report("- nothing changed")
FEEDBACK_REPORT = make_report(replace=("FEEDBACK FOR THE ORCHESTRATOR", "- add a rule to the report skill"))
BAD_REPORT = make_report(skip="OUTSIDE", replace=("FEEDBACK FOR THE ORCHESTRATOR", "- add a rule"))
GATE_CASES = [
    gate("a Read is no Bash call for an exit code", transcript_event(make_report()), True, "holds no Bash call", transcript=(assistant({"type": "tool_use", "id": "r", "name": "Read", "input": {}}),)),
    gate("a broken transcript line is skipped", {**transcript_event(make_report()), "agent_transcript_path": f"{ROOT}/project/broken.jsonl"}, False, files=(("broken.jsonl", "not json\n" + json.dumps(bash_call("t1")) + "\n"),)),
    gate("a block that is no object is skipped", transcript_event(make_report()), False, transcript=(assistant("text"), bash_call("t1"))),
    gate(
        "a message to another agent is no report",
        transcript_event("done"),
        True,
        "missing: Answer",
        transcript=(assistant({"type": "tool_use", "id": "s", "name": "SendMessage", "input": {"message": make_report()}}),),
    ),
    gate(
        "an exit code in a list result counts",
        transcript_event(make_report(replace=("COMPLIANCE", "Gates: the style gate exit 1"))),
        False,
        transcript=(bash_call("t1"), {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": [{"type": "text", "text": "Exit code 1\noutput"}]}]}}),
    ),
    gate("a what line above the table is refused", stop_event(make_report(replace=("REPORT CARD", "**What would have helped:** nothing\n\n" + CARD.split("\n\n")[0] + "\n\n**How I would do it again:** the same"))), True, "must follow the table", lacks='has no "What'),
    gate("an indented line joins its feedback item", stop_event(make_report(replace=("FEEDBACK FOR THE ORCHESTRATOR", "first item\n  more of it\nsecond item"))), False, wrote=(INBOX_NAME, "first item more of it")),
    gate("an unindented line is its own feedback item", stop_event(make_report(replace=("FEEDBACK FOR THE ORCHESTRATOR", "first item\nsecond item"))), False, wrote=(INBOX_NAME, "agent=worker second item")),
    gate("a complete full report is accepted", stop_event(make_report()), False),
    gate("a report with a heading missing goes back", stop_event(make_report(skip="OUTSIDE")), True, "missing: OUTSIDE"),
    gate("a repeated heading goes back", stop_event(make_report() + "\n## Answer\nagain"), True, "duplicated: Answer"),
    gate("a heading in a fence does not count", stop_event(make_report() + "\n```\n## Answer\n```"), False),
    gate(
        "a problem with no cause goes back",
        stop_event(make_report(replace=("PROBLEMS MET", "- it broke"))),
        True,
        "names no cause",
    ),
    gate(
        "a problem with a cause is accepted",
        stop_event(make_report(replace=("PROBLEMS MET", "- it broke (cause: brief); resolved: no"))),
        False,
    ),
    gate(
        "the form's cause list copied whole goes back",
        stop_event(make_report(replace=("PROBLEMS MET", "- it broke (cause: brief | tool)"))),
        True,
        "names no cause",
    ),
    gate(
        "a project's extra cause is accepted",
        stop_event(make_report(replace=("PROBLEMS MET", "- it broke (cause: GPU)"))),
        False,
        config={"report": {"causes": ["GPU"]}},
    ),
    gate("none in Work goes back", stop_event(make_report(replace=("Work", "none"))), True, "Work says none"),
    gate("TBD in Answer goes back", stop_event(make_report(replace=("Answer", "TBD"))), True, "placeholder"),
    gate(
        "a compliance with no exit code goes back",
        stop_event(make_report(replace=("COMPLIANCE", "all fine"))),
        True,
        "COMPLIANCE names no gate",
    ),
    gate(
        "a score out of range goes back",
        stop_event(make_report(replace=("REPORT CARD", CARD.replace("5/5", "9/5")))),
        True,
        "not an integer 1 to 5",
    ),
    gate(
        "a card with no labelled line goes back",
        stop_event(make_report(replace=("REPORT CARD", CARD.split("**What")[0]))),
        True,
        "What would have helped",
    ),
    gate(
        "the short form is enough for a scout",
        stop_event(make_report(headings=SHORT_HEADINGS), agent_type="harness:scout"),
        False,
    ),
    gate(
        "the short form is not enough for a worker",
        stop_event(make_report(headings=SHORT_HEADINGS)),
        True,
        "missing: COMPLIANCE",
    ),
    gate(
        "an unprefixed project role is judged",
        stop_event(make_report(skip="OUTSIDE"), agent_type="worker"),
        True,
        "missing: OUTSIDE",
    ),
    gate("a built-in helper is not judged", stop_event("no headings", agent_type="Explore"), False),
    gate("another plugin's agent is not judged", stop_event("no headings", agent_type="other:worker"), False),
    gate("web-fetch is not judged", stop_event("The page says X.", agent_type="web-fetch"), False),
    gate("a fork is not judged", stop_event("Done.", agent_type="fork"), False),
    gate("general-purpose is not judged by default", stop_event("Done.", agent_type="general-purpose"), False),
    gate("an unknown role is not judged", stop_event("no headings", agent_type="custom"), False),
    gate(
        "report.short adds a role",
        stop_event(make_report(skip="Work"), agent_type="general-purpose"),
        True,
        "missing: Work",
        config={"report": {"short": ["general-purpose"]}},
    ),
    gate(
        "report.short asks only the short form",
        stop_event(make_report(headings=SHORT_HEADINGS), agent_type="general-purpose"),
        False,
        config={"report": {"short": ["general-purpose"]}},
    ),
    gate(
        "report.full adds a role",
        stop_event(make_report(headings=SHORT_HEADINGS), agent_type="custom"),
        True,
        "missing: COMPLIANCE",
        config={"report": {"full": ["custom"]}},
    ),
    gate("a bare cold-reader owes the short form", stop_event(make_report(headings=SHORT_HEADINGS), agent_type="cold-reader"), False),
    gate("a bare reviewer owes the full form", stop_event(make_report(headings=SHORT_HEADINGS), agent_type="reviewer"), True, "missing: COMPLIANCE"),
    gate(
        "out-of-order headings go back",
        stop_event(make_report().replace("## NOT CHECKED\nnone\n", "") .replace("## OUTSIDE\nnone\n", "## OUTSIDE\nnone\n## NOT CHECKED\nnone\n")),
        True,
        "out of order: OUTSIDE",
    ),
    gate(
        "an unterminated fence does not hide later headings",
        stop_event(make_report(replace=("Work", "- output:\n```\nunterminated"))),
        False,
    ),
    *(
        gate(
            f"feedback of {text!r} files nothing",
            stop_event(make_report(replace=("FEEDBACK FOR THE ORCHESTRATOR", text))),
            False,
            not_wrote=(INBOX_NAME, "id="),
        )
        for text in ("none", "N/A", "No feedback.", "None needed.")
    ),
    gate("no project means no gate", stop_event("no headings"), False, config=None),
    gate(
        "a feedback item reaches the inbox",
        stop_event(FEEDBACK_REPORT),
        False,
        wrote=(INBOX_NAME, f"session={SESSION} agent=worker add a rule to the report skill"),
    ),
    gate(
        "a known feedback item is not filed twice",
        stop_event(FEEDBACK_REPORT),
        False,
        files=((INBOX_NAME, f"- id=7ca9ba8e session={SESSION} agent=worker add a rule to the report skill\n"),),
        not_wrote=(INBOX_NAME, "skill\n- id="),
    ),
    gate(
        "another session's item is filed for this one",
        stop_event(FEEDBACK_REPORT),
        False,
        files=((INBOX_NAME, "- id=7ca9ba8e session=other agent=worker add a rule to the report skill\n"),),
        wrote=(INBOX_NAME, f"id=7ca9ba8e session={SESSION} "),
    ),
    gate(
        "the feedback goes to the project a cd left",
        stop_event(FEEDBACK_REPORT),
        False,
        cwd="project/.claude/worktrees/w1",
        project_dir="project",
        wrote=(INBOX_NAME, "add a rule to the report skill"),
    ),
    gate(
        "a feedback item of a report sent back stays out of the inbox",
        stop_event(BAD_REPORT),
        True,
        "missing: OUTSIDE",
        not_wrote=(INBOX_NAME, "add a rule"),
    ),
    gate(
        "an accepted report reaches the ledger",
        stop_event(make_report(replace=("PROBLEMS MET", "- it broke (cause: brief)"))),
        False,
        wrote=("data/ledger.jsonl", '"causes": ["brief"]'),
    ),
    gate(
        "a second send-back still blocks",
        stop_event(BAD_REPORT),
        True,
        "missing: OUTSIDE",
        files=(("data/send-backs/a1.count", "1"),),
        wrote=("data/send-backs/a1.count", "2"),
    ),
    gate(
        "after the last send-back the agent stops with a warning",
        stop_event(BAD_REPORT),
        False,
        "bad report after 3 send-backs",
        files=(("data/send-backs/a1.count", "3"),),
        wrote=("data/ledger.jsonl", '"accepted": false'),
    ),
    gate(
        "a good report after a send-back records the count",
        stop_event(make_report()),
        False,
        files=(("data/send-backs/a1.count", "2"),),
        wrote=("data/ledger.jsonl", '"send_backs": 2'),
    ),
    gate(
        "a report in a handback call is read from the transcript",
        {**stop_event("Done, see the handback."), "agent_transcript_path": "transcript.jsonl"},
        False,
        transcript=(
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "SubagentHandback", "input": {"message": CLEAN_REPORT}}]},
            },
        ),
    ),
    gate(
        "a handback wins over a last message with another heading",
        transcript_event("## Note\nsee the handback"),
        False,
        transcript=(assistant({"type": "tool_use", "name": "SubagentHandback", "input": {"message": CLEAN_REPORT}}),),
    ),
    gate(
        "a text block holding the report is read",
        transcript_event("Done."),
        False,
        transcript=(assistant({"type": "text", "text": CLEAN_REPORT}),),
    ),
    gate(
        "the last report in the transcript is the report",
        transcript_event("Done."),
        True,
        "missing: OUTSIDE",
        transcript=(assistant({"type": "text", "text": CLEAN_REPORT}), assistant({"type": "text", "text": make_report(skip="OUTSIDE")})),
    ),
    gate(
        "a user line holding a filled form does not count",
        transcript_event("done, no report at all"),
        True,
        "missing: Answer",
        transcript=({"type": "user", "message": {"content": [{"type": "text", "text": "Example:\n" + CLEAN_REPORT}]}},),
    ),
    gate(
        "a request replay holding a filled form does not count",
        transcript_event("done, no report at all"),
        True,
        "missing: Answer",
        transcript=({"type": "api-request-blob", "message": {"role": "assistant", "content": [{"type": "text", "text": CLEAN_REPORT}]}},),
    ),
    # The claim check.
    gate(
        "a changed file left out goes back",
        transcript_event(CLEAN_REPORT),
        True,
        "does not name a file",
        transcript=(edit("t1", "src/a.py"),),
    ),
    gate(
        "a changed file named by its project path is accepted",
        transcript_event(work_report("- src/a.py: changed")),
        False,
        transcript=(edit("t1", "src/a.py"),),
    ),
    gate(
        "a changed file named by its absolute path is accepted",
        transcript_event(work_report(f"- {ROOT}/project/src/a.py: changed")),
        False,
        transcript=(edit("t1", f"{ROOT}/project/src/a.py"),),
    ),
    gate(
        "an absolute call path is named by its project path",
        transcript_event(work_report("- src/a.py: changed")),
        False,
        transcript=(edit("t1", f"{ROOT}/project/src/a.py"),),
    ),
    gate(
        "a changed file named with ./ is accepted",
        transcript_event(work_report("- ./src/a.py: changed")),
        False,
        transcript=(edit("t1", "src/a.py"),),
    ),
    gate(
        "another file with the same ending does not name it",
        transcript_event(work_report("- lib/src/a.py and src/a.pyc")),
        True,
        "does not name a file",
        transcript=(edit("t1", "src/a.py"),),
    ),
    gate(
        "a NotebookEdit counts",
        transcript_event(CLEAN_REPORT),
        True,
        "does not name a file",
        transcript=(assistant({"type": "tool_use", "id": "t1", "name": "NotebookEdit", "input": {"notebook_path": "n.ipynb"}}),),
    ),
    gate(
        "a file under the scratch folder is exempt",
        transcript_event(CLEAN_REPORT),
        False,
        config={"guard": {"scratch": "./scratch/"}},
        transcript=(edit("t1", "scratch/a.txt"),),
    ),
    gate(
        "a file that failed to change is not owed",
        transcript_event(CLEAN_REPORT),
        False,
        transcript=(edit("t1", "src/a.py"), {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True}]}}),
    ),
    gate(
        "an exit code with no Bash call goes back",
        transcript_event(make_report()),
        True,
        "no Bash call",
        transcript=(assistant({"type": "text", "text": "thinking"}),),
    ),
    gate(
        "an exit code with a Bash call is accepted",
        transcript_event(make_report()),
        False,
        transcript=(assistant({"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "true"}}),),
    ),
    gate("a READ past the end goes back", stop_event(work_report("READ `AGENTS.md:2`")), True, "past the end"),
    gate("a READ of the last line is accepted", stop_event(work_report("READ `AGENTS.md:1`")), False),
    gate("a READ range checks its end", stop_event(work_report("READ `AGENTS.md:1-2`")), True, "past the end"),
    gate("a READ of a missing file goes back", stop_event(work_report("READ `gone.md:1`")), True, "does not exist"),
    gate("a READ without the backticks is not a claim", stop_event(work_report("READ gone.md:1")), False),
    # report gate: hardening
    gate(
        "an exit code no Bash call ended with goes back",
        transcript_event(make_report()),
        True,
        "no Bash call of the transcript ended with that code",
        transcript=(bash_call("t1"), bash_failed("t1", 1)),
    ),
    gate(
        "an exit code a failed Bash call printed is accepted",
        transcript_event(make_report(replace=("COMPLIANCE", "Gates: the gate exit 1"))),
        False,
        transcript=(bash_call("t1"), bash_failed("t1", 1)),
    ),
    gate(
        "exit 0 is backed by a Bash call that did not fail",
        transcript_event(make_report(replace=("COMPLIANCE", "Gates: a exit 0; b exit 2"))),
        False,
        transcript=(bash_call("t1"), bash_call("t2"), bash_failed("t2", 2)),
    ),
    gate(
        "a READ quote far from the line goes back",
        stop_event(work_report('READ `doc.md:1` "line nine"')),
        True,
        "quotes text that is not on that line",
        files=(("doc.md", NUMBERED),),
    ),
    gate(
        "a READ quote within 3 lines is accepted",
        stop_event(work_report('READ `doc.md:1` "line four"')),
        False,
        files=(("doc.md", NUMBERED),),
    ),
    gate(
        "a READ backtick quote on the line is accepted",
        stop_event(work_report("READ `doc.md:5-6`: `line eight`")),
        False,
        files=(("doc.md", NUMBERED),),
    ),
    gate(
        "a READ with no quote is unchanged",
        stop_event(work_report("READ `doc.md:1`, then more")),
        False,
        files=(("doc.md", NUMBERED),),
    ),
    gate(
        "a DECIDE bullet is filed as an auto item",
        stop_event(make_report(replace=("DECIDE", "- pick a or b: a, cheap; b, slow"))),
        False,
        wrote=(INBOX_NAME, f"agent=worker {AUTO}DECIDE: pick a or b"),
    ),
    gate(
        "an OUTSIDE bullet is filed as an auto item",
        stop_event(make_report(replace=("OUTSIDE", "- change hooks/x.py"))),
        False,
        wrote=(INBOX_NAME, f"agent=worker {AUTO}OUTSIDE: change hooks/x.py"),
    ),
    gate(
        "a Task score of 3 is filed with its title and reason",
        stop_event("# Report: worker, fix the thing\n" + make_report(replace=("REPORT CARD", CARD.replace("5/5 | done", "3/5 | half done")))),
        False,
        wrote=(INBOX_NAME, f"{AUTO}Task score 3 for fix the thing: half done"),
    ),
    gate("a Task score of 4 is not filed", stop_event(make_report(replace=("REPORT CARD", CARD.replace("5/5", "4/5")))), False, not_wrote=(INBOX_NAME, AUTO)),
    gate("none in DECIDE and OUTSIDE files nothing", stop_event(make_report()), False, not_wrote=(INBOX_NAME, AUTO)),
    gate(
        "auto items stop at 5 a report",
        stop_event(make_report(replace=("OUTSIDE", "\n".join(f"- change file{n}" for n in range(7))))),
        False,
        wrote=(INBOX_NAME, f"{AUTO}OUTSIDE: change file4"),
        not_wrote=(INBOX_NAME, "change file5"),
    ),
    gate(
        "the ledger row holds the new fields",
        transcript_event("# Report: worker, fix the thing\n" + work_report("- src/a.py: changed (DERIVED) READ `AGENTS.md:1` and PROBED")),
        False,
        wrote=("data/ledger.jsonl", '"lines_added": 3'),
        transcript=(
            {"type": "assistant", "message": {"model": "claude-x", "content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "src/a.py", "new_string": "a\nb\nc"}}]}},
        ),
    ),
    gate(
        "text with no report is sent back after the wait",
        {**stop_event("I am done"), "agent_transcript_path": "transcript.jsonl"},
        True,
        "breaks the report",
        transcript=(assistant({"type": "text", "text": "I am done"}),),
    ),
    gate(
        "a good report by handback is accepted",
        {**stop_event(""), "agent_transcript_path": "transcript.jsonl", "last_assistant_message": ""},
        False,
        wrote=("data/ledger.jsonl", '"accepted": true'),
        transcript=(assistant({"type": "tool_use", "id": "h1", "name": "SubagentHandback", "input": {"message": CLEAN_REPORT}}),),
    ),
    gate(
        "a heading that is no report does not hide the handback",
        {**stop_event(""), "agent_transcript_path": "transcript.jsonl", "last_assistant_message": "## Notes\nwaiting"},
        False,
        wrote=("data/ledger.jsonl", '"accepted": true'),
        transcript=(assistant({"type": "tool_use", "id": "h1", "name": "SubagentHandback", "input": {"message": CLEAN_REPORT}}),),
    ),
    gate(
        "an edit beside a Bash call does not hide the Bash call",
        transcript_event(work_report("- src/a.py: changed")),
        False,
        transcript=(edit("t1", "src/a.py"), bash_call("b1")),
    ),
    gate(
        "a bad report by handback is not sent back, since the agent has ended",
        {**stop_event(""), "agent_transcript_path": "transcript.jsonl", "last_assistant_message": ""},
        False,
        "it has already ended",
        transcript=(assistant({"type": "tool_use", "id": "h1", "name": "SubagentHandback", "input": {"message": "## Answer\nno"}}),),
    ),
    gate(
        "a bad report by handback still gets its ledger row",
        {**stop_event(""), "agent_transcript_path": "transcript.jsonl", "last_assistant_message": ""},
        False,
        wrote=("data/ledger.jsonl", '"accepted": false'),
        transcript=(assistant({"type": "tool_use", "id": "h1", "name": "SubagentHandback", "input": {"message": "## Answer\nno"}}),),
    ),
    gate(
        "a bad report by text is still sent back",
        {**stop_event("## Answer\nno"), "agent_transcript_path": "transcript.jsonl"},
        True,
        "breaks the report",
        transcript=(assistant({"type": "text", "text": "## Answer\nno"}),),
    ),
    gate(
        "no report in the transcript in time still gets a row",
        {**stop_event(""), "agent_transcript_path": "transcript.jsonl", "last_assistant_message": ""},
        False,
        wrote=("data/ledger.jsonl", '"accepted": false'),
    ),
    gate(
        "a scratch folder exempts only itself from naming changed files",
        transcript_event(work_report("- nothing named")),
        True,
        "does not name a file",
        transcript=(edit("t1", "src/a.py"),),
        config={"guard": {"scratch": "scratch"}},
    ),
    gate(
        "a relative edit path is read from the event's folder",
        {**transcript_event(work_report("- sub/a.py: changed")), "cwd": "@ROOT@/project/sub"},
        False,
        wrote=("data/ledger.jsonl", '"path": "sub/a.py"'),
        transcript=(edit("t1", "a.py"),),
        cwd="project/sub",
    ),
    gate(
        "the ledger row counts the tool turns",
        transcript_event("# Report: worker, fix the thing\n" + work_report("- src/a.py: changed (DERIVED) READ `AGENTS.md:1` and PROBED")),
        False,
        wrote=("data/ledger.jsonl", '"tool_turns": {"turns": 1, "calls": 1, "one_call_turns": 1, "longest_small_run": 0, "small_reads": 0, "repeats": 0}'),
        transcript=(
            {"type": "assistant", "message": {"model": "claude-x", "content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "src/a.py", "new_string": "a"}}]}},
        ),
    ),
    gate(
        "the ledger row holds the model, budget and claim marks",
        transcript_event("# Report: worker, fix the thing\n" + work_report("- src/a.py: changed (DERIVED) READ `AGENTS.md:1` and PROBED")),
        False,
        wrote=("data/ledger.jsonl", '"model": "claude-x", "budget_turns": 70, "files_changed": [{"path": "src/a.py", "lines_added": 3}], "claim_marks": {"READ": 1, "DERIVED": 1, "PROBED": 1}, "brief_hash": "5acca603"'),
        transcript=(
            {"type": "assistant", "message": {"model": "claude-x", "content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "src/a.py", "new_string": "a\nb\nc"}}]}},
        ),
    ),
]


# ===========================================================================
# The turn
# ===========================================================================


def launch(tool_id: str, /, *, is_background: bool = True, is_marked: bool = True) -> tuple[dict, dict]:  # keys are data
    """The transcript lines of an Agent call and its result; a background launch says so in its input or in its result."""

    tool_input: dict[str, object] = {"description": "audit"}
    if is_marked:
        tool_input["run_in_background"] = is_background
    use = {"type": "tool_use", "id": tool_id, "name": "Agent", "input": tool_input}
    reply = "Async agent launched successfully." if is_background else "The agent finished."
    result = {"type": "tool_result", "tool_use_id": tool_id, "content": [{"type": "text", "text": reply}]}

    return (
        {"type": "assistant", "message": {"role": "assistant", "content": [use]}},
        {"type": "user", "message": {"role": "user", "content": [result]}},
    )


def notify(tool_id: str, status: str, /) -> dict:  # keys are data
    body = f"<task-notification>\n<tool-use-id>{tool_id}</tool-use-id>\n<status>{status}</status>\n</task-notification>"

    return {"type": "user", "message": {"role": "user", "content": body}}


def both_notify() -> dict:  # keys are data
    """One user line with two notifications: the launched agent runs on, another one finished."""

    running = notify("t1", "running")["message"]["content"]
    finished = notify("b9", "completed")["message"]["content"]

    return {"type": "user", "message": {"role": "user", "content": running + finished}}


def turn(
    name: str,
    message: str,
    blocks: bool,
    text: str = "",
    /,
    *,
    calls: list[str] | None = None,
    transcript: tuple[dict, ...] = (),
    files: tuple[tuple[str, str], ...] = (),
    **options: object,
) -> Case:
    event = {"session_id": SESSION, "last_assistant_message": message, "transcript_path": "transcript.jsonl"}
    counted = (f"data/turns/{SESSION}.calls", "".join(f"{call}\n" for call in calls or []))
    options.setdefault("config", {})

    return Case(name, ("turn.py", "stop"), event, blocks, text, files=(counted, *files), transcript=transcript, **options)


INBOX = (INBOX_NAME, f"- id=deadbeef session={SESSION} agent=worker add a rule\n")
HANDLED_RULE = (HANDLED_NAME, "deadbeef: rule written in AGENTS.md\n")
BLOCKS_FILE = f"data/turns/{SESSION}.blocks"
CALLS_FILE = f"data/turns/{SESSION}.calls"
RULES_FILE = f"data/turns/{SESSION}.rules"
DEFERRED_FILE = f"data/turns/{SESSION}.deferred"
RELEASED_FILE = f"data/turns/{SESSION}.released"
RELEASED_FILE_ITEM = (RELEASED_FILE, "deadbeef")
RULE_FILE_BEFORE = ("AGENTS.md", "a rule\n")
RULES_KEPT = (RULES_FILE, "{}")
RULES_OTHER = (RULES_FILE, '{"AGENTS.md": "changed since"}')
LESSONS = "Done.\n\n**Lessons:** the brief was vague, so a rule is needed.\n"
# No rule path: the state now is `{}`, so RULES_KEPT means nothing changed and RULES_OTHER that something did.
NO_RULE_PATHS = {"stop": {"rule_paths": []}}
TURN_CASES = [
    turn("the status is read from the transcript when the event has none", "", False, calls=BUSY_CALLS, transcript=(assistant({"type": "text", "text": FULL_STATUS}),)),
    turn("a last line that is a tool call does not crash", "", False, transcript=(assistant({"type": "text", "text": "Done."}), assistant({"type": "tool_use", "id": "t", "name": "Bash", "input": {}}))),
    Case("no mode does nothing", ("turn.py",), {"session_id": SESSION}, False, config={}),
    turn("a progress note with a background agent running is allowed", PROGRESS, False, calls=BUSY_CALLS, transcript=launch("t1")),
    turn(
        "a background agent marked only by its result counts as running",
        PROGRESS,
        False,
        calls=BUSY_CALLS,
        transcript=launch("t1", is_marked=False),
    ),
    turn(
        "one of two background agents still running is allowed",
        PROGRESS,
        False,
        calls=BUSY_CALLS,
        transcript=(*launch("t1"), *launch("t2"), notify("t1", "completed")),
    ),
    turn(
        "all agents completed and no status is refused",
        PROGRESS,
        True,
        "Verdict",
        calls=BUSY_CALLS,
        transcript=(*launch("t1"), *launch("t2"), notify("t1", "completed"), notify("t2", "completed")),
    ),
    turn("a failed agent is finished", PROGRESS, True, "Verdict", calls=BUSY_CALLS, transcript=(*launch("t1"), notify("t1", "failed"))),
    turn("a killed agent is finished", PROGRESS, True, "Verdict", calls=BUSY_CALLS, transcript=(*launch("t1"), notify("t1", "killed"))),
    turn("a foreground agent never runs on", PROGRESS, True, "Verdict", calls=BUSY_CALLS, transcript=launch("t1", is_background=False)),
    turn("no agent and no status is refused", PROGRESS, True, "Needs you", calls=BUSY_CALLS),
    turn("the full status with no agent is allowed", FULL_STATUS + "\nLessons: none", False, calls=BUSY_CALLS, files=(RULES_KEPT,)),
    turn("two calls need no status", PROGRESS, False, calls=["Edit", "Edit"]),
    turn("a heading in a fence does not count", f"```\n{FULL_STATUS}\n```", True, "Verdict", calls=BUSY_CALLS),
    turn("a project's min_calls is read", PROGRESS, False, calls=BUSY_CALLS, config={"stop": {"min_calls": 5}}),
    turn("no project means no gate", PROGRESS, False, calls=BUSY_CALLS, config=None),
    turn("an unhandled feedback id is refused", PROGRESS, True, "deadbeef", files=(INBOX,)),
    turn("a handled feedback id is allowed", PROGRESS, False, files=(INBOX, HANDLED_RULE)),
    turn("a rejected feedback id is allowed", PROGRESS, False, files=(INBOX, (HANDLED_NAME, "deadbeef: rejected: it does not apply\n"))),
    turn("a handled line with no verdict does not count", PROGRESS, True, "deadbeef", files=(INBOX, (HANDLED_NAME, "deadbeef: looked\n"))),
    turn("a missing inbox is no error", PROGRESS, False),
    turn("lessons with no rule change are refused", LESSONS, True, "no change to show", files=(RULES_KEPT,), config=NO_RULE_PATHS),
    turn("lessons that defer are refused", "**Lessons:** will add a rule next turn.\n", True, "defers", files=(RULES_KEPT,), config=NO_RULE_PATHS),
    turn("lessons with a rule change are allowed", LESSONS, False, files=(RULES_OTHER,), config=NO_RULE_PATHS),
    turn("Lessons: none is allowed", "Lessons: none\n", False, files=(RULES_KEPT,), config=NO_RULE_PATHS),
    turn(
        "the third block is the last",
        PROGRESS,
        True,
        "deadbeef",
        files=(INBOX, (BLOCKS_FILE, "2")),
        wrote=(BLOCKS_FILE, "3"),
    ),
    turn(
        "past the last block the turn ends with a warning",
        PROGRESS,
        False,
        "open checks",
        files=(INBOX, (BLOCKS_FILE, "3")),
        wrote=(RELEASED_FILE, "deadbeef"),
    ),
    turn("a released id holds no more, with no warning", PROGRESS, False, files=(INBOX, (RELEASED_FILE, "deadbeef")), lacks="open checks"),
    turn(
        "a released id does not release a newer one",
        PROGRESS,
        True,
        "cafef00d",
        files=(RELEASED_FILE_ITEM, (INBOX_NAME, f"- id=deadbeef session={SESSION} agent=w a\n- id=cafef00d session={SESSION} agent=w b\n")),
        lacks="ids deadbeef",
    ),
    turn("an old line with no session never blocks", PROGRESS, False, files=((INBOX_NAME, "- id=deadbeef agent=worker add a rule\n"),)),
    turn("another session's line never blocks", PROGRESS, False, files=((INBOX_NAME, "- id=deadbeef session=other agent=worker a\n"),)),
    turn("a pass resets the blocks", PROGRESS, False, files=((BLOCKS_FILE, "2"),), wrote=(BLOCKS_FILE, "0")),
    turn("a background Agent with no result yet is running", PROGRESS, False, calls=BUSY_CALLS, transcript=(launch("t1")[0],)),
    turn(
        "a background Bash is no running agent",
        PROGRESS,
        True,
        calls=BUSY_CALLS,
        transcript=(assistant({"type": "tool_use", "id": "b1", "name": "Bash", "input": {"run_in_background": True}}),),
    ),
    turn(
        "a user line is no closing message",
        "",
        True,
        calls=BUSY_CALLS,
        transcript=(assistant({"type": "text", "text": PROGRESS}), {"type": "user", "message": {"content": [{"type": "text", "text": FULL_STATUS}]}}),
    ),
    turn(
        "a sub-agent's message keeps the rule baseline",
        "## Verdict\nx\n## Lessons\n- a lesson written down",
        False,
        before=((("turn.py", "reset"), {"session_id": SESSION}), (("rewrite.py",), {"path": "AGENTS.md", "text": "a new rule\n"}), (("turn.py", "reset"), {"session_id": SESSION, "prompt": 'Another Claude session sent a message:\n<agent-message from="a1">'})),
    ),
    turn(
        "a notification keeps the rule baseline",
        "## Verdict\nx\n## Lessons\n- a lesson written down",
        False,
        before=((("turn.py", "reset"), {"session_id": SESSION}), (("rewrite.py",), {"path": "AGENTS.md", "text": "a new rule\n"}), (("turn.py", "reset"), {"session_id": SESSION, "prompt": "<task-notification>\n<status>completed</status>"})),
    ),
    turn(
        "the owner's new prompt moves the rule baseline",
        "## Verdict\nx\n## Lessons\n- a lesson written down",
        True,
        "no change to show",
        before=((("turn.py", "reset"), {"session_id": SESSION}), (("rewrite.py",), {"path": "AGENTS.md", "text": "a new rule\n"}), (("turn.py", "reset"), {"session_id": SESSION, "prompt": "go on"})),
    ),
    turn("a progress note keeps the count", PROGRESS, False, calls=BUSY_CALLS, transcript=launch("t1"), wrote=(CALLS_FILE, "Agent"), config={}),
    turn("a progress note marks the status as due", PROGRESS, False, calls=BUSY_CALLS, transcript=launch("t1"), wrote=(DEFERRED_FILE, "1")),
    turn("the status empties the count", FULL_STATUS + "\nLessons: none", False, calls=BUSY_CALLS, files=(RULES_KEPT,), not_wrote=(CALLS_FILE, "Agent")),
    turn(
        "the status clears the due mark",
        FULL_STATUS + "\nLessons: none",
        False,
        calls=BUSY_CALLS,
        files=(RULES_KEPT, (DEFERRED_FILE, "1")),
        not_wrote=(DEFERRED_FILE, "1"),
    ),
    turn(
        "a running status of the agent is no finish, whatever else finished",
        PROGRESS,
        False,
        calls=BUSY_CALLS,
        transcript=(*launch("t1"), notify("t1", "running"), notify("b9", "completed")),
    ),
    turn(
        "a notification in one message pairs each id with its own status",
        PROGRESS,
        False,
        calls=BUSY_CALLS,
        transcript=(*launch("t1"), both_notify()),
    ),
    turn("a fence that never closes does not hide the status", FULL_STATUS + "\nLessons: none\n```\nopen", False, calls=BUSY_CALLS, files=(RULES_KEPT,)),
    turn("the project variable counts past a cd", PROGRESS, True, "Verdict", calls=BUSY_CALLS, cwd="elsewhere", project_dir="project"),
    # The rule state, from a real reset.
    turn(
        "a rule file dirty at the start and left the same is no change",
        LESSONS,
        True,
        "no change to show",
        files=(("AGENTS.md", "dirty rule\n"),),
        before=((("turn.py", "reset"), {"session_id": SESSION}),),
    ),
    turn(
        "a whitespace change is no change",
        LESSONS,
        True,
        "no change to show",
        files=((RULE_FILE_BEFORE),),
        before=((("turn.py", "reset"), {"session_id": SESSION}), (("rewrite.py",), {"path": "AGENTS.md", "text": "a  rule\n\n"})),
    ),
    turn(
        "a rule file changed this turn counts",
        LESSONS,
        False,
        files=((RULE_FILE_BEFORE),),
        before=((("turn.py", "reset"), {"session_id": SESSION}), (("rewrite.py",), {"path": "AGENTS.md", "text": "a new rule\n"})),
    ),
    turn(
        "a file in .claude counts",
        LESSONS,
        False,
        files=((".claude/rules/a.md", "old\n"),),
        before=((("turn.py", "reset"), {"session_id": SESSION}), (("rewrite.py",), {"path": ".claude/rules/a.md", "text": "new\n"})),
    ),
    turn(
        "a file in a worktree under .claude is no rule file",
        LESSONS,
        True,
        "no change to show",
        files=((".claude/worktrees/w/code.py", "a = 1\n"),),
        before=((("turn.py", "reset"), {"session_id": SESSION}), (("rewrite.py",), {"path": ".claude/worktrees/w/code.py", "text": "a = 2\n"})),
    ),
    Case(
        "add counts a call of the session",
        ("turn.py", "add"),
        {"session_id": SESSION, "tool_name": "Edit"},
        False,
        config={},
        files=((f"data/turns/{SESSION}.calls", "Agent\n"),),
        wrote=(f"data/turns/{SESSION}.calls", "Agent\nEdit\n"),
    ),
    Case(
        "add ignores a call of a sub-agent",
        ("turn.py", "add"),
        {"session_id": SESSION, "tool_name": "Edit", "agent_id": "a1"},
        False,
        config={},
        files=((f"data/turns/{SESSION}.calls", "Agent\n"),),
        not_wrote=(f"data/turns/{SESSION}.calls", "Edit"),
    ),
    Case(
        "reset empties the count and saves the rule state",
        ("turn.py", "reset"),
        {"session_id": SESSION},
        False,
        config={},
        files=((f"data/turns/{SESSION}.calls", "Agent\nEdit\n"), ("AGENTS.md", "a rule\n")),
        not_wrote=(f"data/turns/{SESSION}.calls", "Agent"),
        wrote=(f"data/turns/{SESSION}.rules", "AGENTS.md"),
    ),
    Case(
        "reset keeps the count when a status is due",
        ("turn.py", "reset"),
        {"session_id": SESSION, "prompt": "<task-notification>"},
        False,
        config={},
        files=((CALLS_FILE, "Agent\nEdit\n"), (DEFERRED_FILE, "1"), (RULES_FILE, '{"kept": "x"}')),
        wrote=(CALLS_FILE, "Agent\nEdit\n"),
    ),
    Case(
        "reset keeps the turn's rule state when a status is due",
        ("turn.py", "reset"),
        {"session_id": SESSION},
        False,
        config={},
        files=((DEFERRED_FILE, "1"), (RULES_FILE, '{"kept": "x"}')),
        wrote=(RULES_FILE, "kept"),
    ),
    Case(
        "reset still zeroes the blocks when a status is due",
        ("turn.py", "reset"),
        {"session_id": SESSION},
        False,
        config={},
        files=((DEFERRED_FILE, "1"), (BLOCKS_FILE, "3")),
        wrote=(BLOCKS_FILE, "0"),
    ),
    Case(
        "add does nothing with no project",
        ("turn.py", "add"),
        {"session_id": SESSION, "tool_name": "Edit"},
        False,
        not_wrote=(f"data/turns/{SESSION}.calls", "Edit"),
    ),
]


# ===========================================================================
# The delegate rule
# ===========================================================================


def main_call(name: str, tool: str, tool_input: dict, blocks: bool, text: str = "", /, *, settings: object = None, **options: object) -> Case:  # keys are data
    """A call of the main session under the delegate rule; `settings` is its `delegate` key, empty by default."""

    options.setdefault("config", {"delegate": settings if settings is not None else {}})

    return Case(name, ("delegate.py",), {"tool_name": tool, "agent_id": None, "tool_input": tool_input}, blocks, text, **options)


def main_bash(name: str, command: str, blocks: bool, /, **options: object) -> Case:
    return main_call(name, "Bash", {"command": command}, blocks, "main-session commands" if blocks else "", **options)


ONLY_DOCS = {"write_allow": ["docs/*"], "bash_allow": ["make check"]}
DELEGATE_CASES = [
    main_call("an edit with an empty allow list is refused", "Edit", {"file_path": "src/a.py"}, True, "write_allow"),
    main_call("a write outside the allow list is refused", "Write", {"file_path": "src/a.py"}, True, "write_allow", settings=ONLY_DOCS),
    main_call("a write inside the allow list is allowed", "Write", {"file_path": "docs/a.md"}, False, settings=ONLY_DOCS),
    main_call("a notebook edit outside is refused", "NotebookEdit", {"notebook_path": "n.ipynb"}, True, "write_allow", settings=ONLY_DOCS),
    main_call("an absolute path inside the allow list is allowed", "Write", {"file_path": f"{ROOT}/project/docs/b.md"}, False, settings=ONLY_DOCS),
    main_call("a symlinked path is read resolved", "Write", {"file_path": "link/a.py"}, True, "write_allow", settings=ONLY_DOCS, links=(("project/link", "project/src"),)),
    main_call("a path outside the project is refused whatever the glob", "Write", {"file_path": "../x"}, True, "write_allow", settings={"write_allow": ["*"]}),
    main_call("the handled file is always allowed", "Edit", {"file_path": "harness-feedback/handled.md"}, False),
    main_call("the inbox is not", "Edit", {"file_path": "harness-feedback/inbox.md"}, True, "write_allow"),
    Case("a sub-agent's edit passes", ("delegate.py",), {"tool_name": "Edit", "agent_id": "a1", "tool_input": {"file_path": "src/a.py"}}, False, config={"delegate": {}}),
    Case("a sub-agent's command passes", ("delegate.py",), {"tool_name": "Bash", "agent_id": "a1", "tool_input": {"command": "make x"}}, False, config={"delegate": {}}),
    main_call("no delegate key means no rule", "Edit", {"file_path": "src/a.py"}, False, config={}),
    main_call("no project means no rule", "Edit", {"file_path": "src/a.py"}, False, config=None),
    *(main_bash(f"delegate allows: {command!r}", command, False) for command in (
        "git status",
        "git log -3",
        "git diff HEAD~1",
        "git show HEAD",
        "git add -A",
        "git commit -m x",
        "gh pr list",
        "ls -la",
        "rg x src",
        "head -3 a.txt",
        "wc -l a.txt",
        "git status && git log -3 | head -3",
        COMMIT.format(body="subject\n\nbody 1) with \"quotes\""),
        "git log > /dev/null 2>&1",
    )),
    *(main_bash(f"delegate refuses: {command!r}", command, True) for command in (
        "git logs",
        "git status && make x",
        "make x; git status",
        "git log $(make x)",
        "make x",
        "cat a.txt",
        "git log > out.txt",
        "> out.txt",
    )),
    main_bash("a push is refused by default", "git push origin topic", True),
    main_bash("a push is refused after other defaults", "git add -A && git push", True),
    main_bash("a project may list a push", "git push origin topic", False, settings={"bash_allow": ["git push"]}),
    main_bash("add and commit pass by default", "git add -A && git commit -m x", False),
    main_bash("bash_allow adds a prefix", "make check -j2", False, settings=ONLY_DOCS),
    main_bash("bash_allow matches whole words", "make checks", True, settings=ONLY_DOCS),
    main_bash("bash_allow keeps the default list", "git status", False, settings=ONLY_DOCS),
    main_bash("the project variable pins the rule", "make x", True, cwd="elsewhere", project_dir="project"),
    Case(
        "a broken config lets the main session's call run",
        ("delegate.py",),
        {"tool_name": "Bash", "tool_input": {"command": "make x"}},
        False,
        "delegate rule failed",
        files=((".harness.json", "{not json"),),
        is_exit_one=True,
    ),
]


# ===========================================================================
# The brief rule
# ===========================================================================


def brief(name: str, role: str, prompt: str, blocks: bool, text: str = "", /, **options: object) -> Case:  # keys are data
    options.setdefault("config", {"brief": {}})
    event = {"tool_name": "Agent", "tool_input": {"subagent_type": role, "prompt": prompt}}

    return Case(name, ("brief_lint.py",), event, blocks, text, **options)


GOOD_BRIEF = "Do it.\nGoal: x\nWrite set: y\nJudge: z\n"
BRIEF_CASES = [
    brief("a fence with a language hides a budget", "scout", "Goal: x\n```python\nBudget: 5 minutes\n```", False),
    brief("a whole worker brief passes", "worker", GOOD_BRIEF, False),
    brief("a budget in minutes is refused", "scout", "Goal: x\nBudget: 5 minutes", True, "counts model turns"),
    brief("a budget in a sentence in minutes is refused", "scout", "Goal: x. Budget: 40 minutes. Folder: a", True, "counts model turns"),
    brief("a budget in turns passes", "scout", "Goal: x\nBudget: 5 turns", False),
    brief("a bare budget passes", "scout", "Goal: x\nBudget: 5", False),
    brief("a sentence opening with the word passes", "scout", "Goal: x\nBudget is 30 turns, roughly", False),
    brief("prose about a budget passes", "scout", "Goal: x\nWe are over budget: three things", False),
    brief("a quoted budget passes", "scout", "Goal: x\nThe old form was `Do x. Budget: 5 minutes` here", False),
    brief("a budget in a fence passes", "scout", "Goal: x\n```\nBudget: 5 minutes\n```", False),
    brief("a prefixed worker is the worker", "harness:worker", "Goal: x", True, "Write set:"),
    brief("a worker brief without Judge is refused", "worker", "Goal: x\nWrite set: y", True, "Judge:"),
    brief("a worker brief without Write set is refused", "worker", "Goal: x\nJudge: y", True, "Write set:"),
    brief("a label in the middle of a line does not count", "scout", "The Goal: is x", True, "Goal:"),
    brief("a bold label counts", "scout", "**Goal:** x", False),
    brief("a scout needs Goal", "scout", "Look at x", True, "Goal:"),
    brief("a prefixed reviewer needs Goal", "harness:reviewer", "Look at x", True, "Goal:"),
    brief("a scout with Goal passes", "scout", "Goal: x", False),
    brief("another agent type passes", "Explore", "Look at x", False),
    brief("another plugin's worker passes", "other:worker", "Look at x", False),
    brief("no subagent type passes", "", "Look at x", False),
    brief("no brief key means no rule", "worker", "Look at x", False, config={}),
    brief("no project means no rule", "worker", "Look at x", False, config=None),
    brief(
        "brief.required replaces the default",
        "worker",
        "Goal: x",
        True,
        "Plan:",
        config={"brief": {"required": {"worker": ["Plan:"], "*": []}}},
    ),
    brief("brief.required with no entry for a role asks nothing", "scout", "Look", False, config={"brief": {"required": {"worker": ["Goal:"]}}}),
    Case(
        "a sub-agent's call passes",
        ("brief_lint.py",),
        {"tool_name": "Agent", "agent_id": "a1", "tool_input": {"subagent_type": "worker", "prompt": "x"}},
        False,
        config={"brief": {}},
    ),
]


# ===========================================================================
# The budget rule
# ===========================================================================

OLD, NEW = "2020-01-01T00:00:00.000Z", "2999-01-01T00:00:00.000Z"


def budget(name: str, brief_text: str, blocks: bool, text: str = "", /, *, turns: int = 100, role: str = "harness:worker", **options: object) -> Case:  # keys are data
    """A sub-agent's call after `turns` model turns; its transcript is `s/subagents/agent-a1.jsonl` beside the session's `s.jsonl`."""

    first = {"type": "user", "timestamp": OLD, "message": {"role": "user", "content": brief_text}}
    lines = [json.dumps({"type": "assistant", "timestamp": NEW, "message": {"id": f"m{index}", "content": [{"type": "tool_use", "id": f"t{index}", "name": "Bash", "input": {}}]}}) for index in range(turns)]
    options.setdefault("config", {})
    options.setdefault("files", (("s/subagents/agent-a1.jsonl", json.dumps(first) + "\n" + "\n".join(lines) + "\n"),))
    event = {"tool_name": "Bash", "agent_id": "a1", "agent_type": role, "transcript_path": "project/s.jsonl", "tool_use_id": f"t{turns - 1}"}

    return Case(name, ("budget.py",), {**event, **options.pop("event", {})}, blocks, text, **options)


BUDGET_CASES = [
    budget("a note comes with a fifth of the budget left", "Budget: 30", False, "6 of your 30 turns are left", turns=24),
    budget("the note is hook context", "Budget: 30", False, '"hookEventName": "PreToolUse", "additionalContext": "Harness note', turns=24),
    budget("no note one turn before", "Budget: 30", False, lacks="additionalContext", turns=23),
    budget("no note one turn after", "Budget: 30", False, lacks="additionalContext", turns=25),
    budget("a small budget gets its note at three left", "Budget: 6", False, "3 of your 6 turns are left", turns=3),
    budget("a worker past its default budget is refused", "Goal: x", True, "Send your report now"),
    budget("the refusal counts the turns", "Goal: x", True, "budget of 70 turns is spent (100 turns so far)"),
    budget("the refusal asks for a partial report", "Goal: x", True, "done, not done, what is on disk"),
    budget("a worker at its default budget passes", "Goal: x", False, turns=70),
    budget("a worker one turn past it is refused", "Goal: x", True, turns=71),
    budget("calls of one message are one turn", "Budget: 1", False, files=(("s/subagents/agent-a1.jsonl", json.dumps({"timestamp": OLD, "message": {"content": "Budget: 1"}}) + "\n" + "".join(json.dumps({"type": "assistant", "message": {"id": "m1", "content": [{"type": "tool_use", "id": call, "name": "Read"}]}}) + "\n" for call in ("a", "b", "c"))),), event={"tool_use_id": "c"}),
    budget("a call not yet in the transcript counts as a turn", "Goal: x", True, "71 turns so far", turns=70, event={"tool_use_id": "new"}),
    budget("an event with no call id counts what is written", "Goal: x", False, turns=70, event={"tool_use_id": None}),
    budget("the brief's Budget line replaces the default", "Goal: x\nBudget: 99999999", False),
    budget("a short Budget line refuses early", "Goal: x\nBudget: 1", True, "1 turns", turns=2, config={"budget": {"worker": 99999999}}),
    budget("Budget: N turns counts", "Goal: x\nBudget: 99999999 turns", False),
    budget("Budget: 1 turn counts", "Goal: x\n- **Budget:** 1 turn", True, turns=2, config={"budget": {"worker": 99999999}}),
    budget("a Budget line in a fence does not count", "Goal: x\n```\nBudget: 99999999\n```", True),
    budget("the budget ends its own sentence", "Goal: x\nBudget: 99999999 turns. Throwaway folder: `scratch/a/`.", False),
    budget("the budget sits inside a line", "Runs: smallest first. Budget: 99999999 turns. Folder: a", False),
    budget("a budget in minutes is no budget", "Goal: x\nBudget: 99999999 minutes", True),
    budget("a number of something else is no budget", "Goal: x\nBudget: 99999999 files", True),
    budget("a quoted budget is no budget", "Goal: x, the line read is `Budget: 99999999`", True),
    budget("a budget quoted after other text is no budget", "Goal: x\nPut `Do this. Budget: 99999999 turns` in it.", True),
    budget("a budget at the end of prose is no budget", "Goal: x, we are over budget: 99999999", True),
    budget("a budget inside a sentence is no budget", "Spend no budget 99999999 turns on it", True),
    budget("a handback past the budget passes", "Goal: x", False, event={"tool_name": "SubagentHandback"}),
    budget("a scout at 35 turns passes", "Goal: x", False, role="scout", turns=35),
    budget("a scout is refused past 35 turns", "Goal: x", True, role="scout", turns=36),
    budget("the project's budget replaces the defaults", "Goal: x", False, config={"budget": {"worker": 99999999}}),
    budget("a role with no budget entry passes", "Goal: x", False, config={"budget": {"scout": 1}}),
    budget("another agent type with no line passes", "Goal: x", False, role="Explore"),
    budget("another agent type with a line is refused", "Goal: x\nBudget: 1", True, role="Explore"),
    budget("the main session passes", "Goal: x", False, event={"agent_id": None, "agent_transcript_path": "project/s/subagents/agent-a1.jsonl"}),
    budget("no project means no rule", "Goal: x", False, config=None),
    budget("a missing transcript passes", "Goal: x", False, files=()),
    budget(
        "a list brief is read",
        "",
        True,
        files=(("s/subagents/agent-a1.jsonl", json.dumps({"timestamp": OLD, "message": {"content": [{"type": "text", "text": "Budget: 0"}]}}) + "\n" + json.dumps({"type": "assistant", "message": {"id": "m", "content": [{"type": "tool_use", "id": "t", "name": "Read"}]}}) + "\n"),),
        config={"budget": {"worker": 99999999}},
    ),
    budget("a broken transcript lets the call run", "", False, files=(("s/subagents/agent-a1.jsonl", "{not json\n"),), is_exit_one=True),
    Case(
        "the ledger row holds the duration",
        ("report_gate.py",),
        {**stop_event(make_report()), "transcript_path": "project/s.jsonl"},
        False,
        files=(("s/subagents/agent-a1.jsonl", json.dumps({"timestamp": "2026-01-01T00:00:00Z"}) + "\n" + json.dumps({"timestamp": "2026-01-01T00:03:30.5Z"}) + "\n"),),
        wrote=("data/ledger.jsonl", '"duration_s": 210.5'),
        config={},
    ),
    Case(
        "the ledger row's duration is null when unknown",
        ("report_gate.py",),
        stop_event(make_report()),
        False,
        wrote=("data/ledger.jsonl", '"duration_s": null'),
        config={},
    ),
]


# ===========================================================================
# The tool-turn nudge
# ===========================================================================


def read_call(call_id: str, path: str = "", /) -> dict:  # keys are data
    return {"type": "tool_use", "id": call_id, "name": "Read", "input": {"file_path": path or f"{call_id}.py"}}


def shell_call(call_id: str, command: str, /) -> dict:  # keys are data
    return {"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}


def make_reads(count: int, /) -> list[list[dict]]:  # keys are data
    return [[read_call(f"r{index}")] for index in range(count)]


def nudge(name: str, turns: list[list[dict]], text: str = "", /, *, path: str = "s/subagents/agent-a1.jsonl", **options: object) -> Case:  # keys are data
    """A PostToolUse event for a sub-agent whose transcript at `path` holds `turns`, each the calls of one message; it names the last call."""

    lines = [json.dumps({"type": "assistant", "message": {"id": f"m{index}", "content": [call]}}) for index, turn in enumerate(turns) for call in turn]
    options.setdefault("config", {})
    options.setdefault("files", ((path, "\n".join(lines) + "\n"),))
    event = {"hook_event_name": "PostToolUse", "tool_name": "Read", "agent_id": "a1", "agent_type": "harness:worker", "transcript_path": "project/s.jsonl", "tool_use_id": turns[-1][-1]["id"]}

    return Case(name, ("nudge.py",), {**event, **options.pop("event", {})}, False, text, **options)


REPEATED = [[read_call("r0", "a.py")], [read_call("r1", "a.py")], [read_call("r2", "a.py")], [read_call("r3", "a.py")]]
NUDGE_CASES = [
    nudge(
        "a repeat with its keys in another order is a repeat",
        [[{"type": "tool_use", "id": "r0", "name": "Read", "input": {"file_path": "a.py", "limit": 1}}], [{"type": "tool_use", "id": "r1", "name": "Read", "input": {"limit": 1, "file_path": "a.py"}}]],
        "already made this same read",
    ),
    nudge("four single reads in a row are nudged", make_reads(4), "one small read each"),
    nudge("the nudge is hook context", make_reads(4), '"hookEventName": "PostToolUse"'),
    nudge("three single reads are not", make_reads(3), lacks="additionalContext"),
    nudge("two reads in one message break the run", [*make_reads(3), [read_call("x1"), read_call("x2")]], lacks="additionalContext", event={"tool_use_id": "x1"}),
    nudge("a batched command breaks the run", [*make_reads(3), [shell_call("b1", "cat a; cat b")]], lacks="additionalContext"),
    nudge("a sed -i is no read", [[shell_call(f"b{index}", f"sed -i s/a/b/ f{index}.py")] for index in range(4)], lacks="additionalContext"),
    nudge("single shell reads count", [[shell_call(f"b{index}", f"cd /repo && cat f{index}.py")] for index in range(4)], "one small read each"),
    nudge("a read after cd and a semicolon counts", [[shell_call(f"b{index}", f"cd /repo; cat f{index}.py")] for index in range(4)], "one small read each"),
    nudge(
        "a line with no call does not break the run",
        make_reads(4),
        "one small read each",
        files=(("s/subagents/agent-a1.jsonl", "".join(json.dumps({"type": "assistant", "message": {"id": f"m{index}", "content": [call]}}) + "\n" + json.dumps({"type": "assistant", "message": {"id": f"t{index}", "content": [{"type": "text", "text": "x"}]}}) + "\n" for index, [call] in enumerate(make_reads(4)))),),
    ),
    nudge("a repeated read is nudged", REPEATED[:2], "same read"),
    nudge("the same read after a command is a repeat", [REPEATED[0], [shell_call("c1", "python3 x.py")], REPEATED[1]], "same read"),
    nudge("the same read after an edit is not", [REPEATED[0], [{"type": "tool_use", "id": "e1", "name": "Edit", "input": {}}], REPEATED[1]], lacks="additionalContext"),
    nudge("another range of the file is not a repeat", [[read_call("r0", "a.py")], [{"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": "a.py", "offset": 9}}]], lacks="additionalContext"),
    nudge("the second nudge still speaks", REPEATED[:3], "same read"),
    nudge("the third nudge is silent", REPEATED, lacks="additionalContext"),
    nudge("a call that is not the wasteful one hears nothing", REPEATED[:2], lacks="additionalContext", event={"tool_use_id": "r0"}),
    nudge("the main session is nudged from its transcript", REPEATED[:2], "same read", path="s.jsonl", event={"agent_id": None}),
    nudge("a sub-agent is not judged by the session's transcript", REPEATED[:2], lacks="additionalContext", path="s.jsonl"),
    nudge("no project means no nudge", REPEATED[:2], lacks="additionalContext", config=None),
    nudge(
        "a transcript past the size limit gets no nudge",
        REPEATED[:2],
        lacks="additionalContext",
        files=(("s/subagents/agent-a1.jsonl", json.dumps({"type": "user", "message": {"content": "x" * 1048576}}) + "\n" + "".join(json.dumps({"type": "assistant", "message": {"id": f"m{index}", "content": turn}}) + "\n" for index, turn in enumerate(REPEATED[:2]))),),
    ),
    nudge("a missing transcript passes", REPEATED[:2], lacks="additionalContext", files=()),
    nudge("a torn transcript line is skipped", REPEATED[:2], lacks="additionalContext", files=(("s/subagents/agent-a1.jsonl", "{not json\n"),)),
    nudge("a broken config lets the call run", REPEATED[:2], lacks="additionalContext", config=None, files=((".harness.json", "{not json"),), is_exit_one=True),
]


# ===========================================================================
# The import and replay tools
# ===========================================================================


IMPORT_SOURCE = "../.claude/projects/p/s/subagents/agent-a1.jsonl"
IMPORT_LINES = (
    {"type": "assistant", "timestamp": NEW, "cwd": "/w", "sessionId": "s", "message": {"id": "m1", "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "a"}}]}},
    {"type": "assistant", "timestamp": NEW, "cwd": "/w", "sessionId": "s", "message": {"id": "m2", "content": [{"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "b"}}]}},
    {"type": "assistant", "timestamp": NEW, "message": {"id": "m3", "content": [{"type": "text", "text": make_report()}]}},
)
IMPORT_TEXT = "".join(json.dumps(line) + "\n" for line in IMPORT_LINES)
TOOL_CASES = [
    Case("a handback's message is the report", ("import_reports.py",), {}, False, "to add: 1", files=((IMPORT_SOURCE, json.dumps({"type": "assistant", "timestamp": NEW, "message": {"id": "m", "content": [{"type": "tool_use", "id": "h", "name": "SubagentHandback", "input": {"message": make_report()}}]}})),)),
    Case("another tool's message is no report", ("import_reports.py",), {}, False, "with a report card: 0", files=((IMPORT_SOURCE, json.dumps({"type": "assistant", "timestamp": NEW, "message": {"id": "m", "content": [{"type": "tool_use", "id": "s", "name": "SendMessage", "input": {"message": make_report()}}]}})),)),
    Case("a report in a user line is no report", ("import_reports.py",), {}, False, "with a report card: 0", files=((IMPORT_SOURCE, json.dumps({"type": "user", "timestamp": NEW, "message": {"content": [{"type": "text", "text": make_report()}]}})),)),
    Case("a line with no content does not hide the report", ("import_reports.py",), {}, False, "to add: 1", files=((IMPORT_SOURCE, IMPORT_TEXT + json.dumps({"type": "assistant", "timestamp": NEW, "message": {"id": "m4", "content": None}})),)),
    Case("an imported report becomes a row", ("import_reports.py",), {}, False, "to add: 1", files=((IMPORT_SOURCE, IMPORT_TEXT),), wrote=("data/ledger.jsonl", '"imported": true')),
    Case("an imported row counts its tool turns", ("import_reports.py",), {}, False, files=((IMPORT_SOURCE, IMPORT_TEXT),), wrote=("data/ledger.jsonl", '"tool_turns": {"turns": 2, "calls": 2, "one_call_turns": 2, "longest_small_run": 2, "small_reads": 2, "repeats": 0}')),
    Case("a transcript with no report card is no row", ("import_reports.py",), {}, False, "with a report card: 0", files=((IMPORT_SOURCE, json.dumps(IMPORT_LINES[0]) + "\n"),), not_wrote=("data/ledger.jsonl", "imported")),
    Case("a dry run writes nothing", ("import_reports.py", "--dry-run"), {}, False, "to add: 1", files=((IMPORT_SOURCE, IMPORT_TEXT),), not_wrote=("data/ledger.jsonl", "imported")),
    Case("a second import adds nothing", ("import_reports.py",), {}, False, "to add: 0", files=((IMPORT_SOURCE, IMPORT_TEXT),), before=((("import_reports.py",), {}),)),
    Case("the replay counts a refused command", ("replay.py",), {}, False, "refused: 1 distinct", files=(("../.claude/projects/p/s.jsonl", json.dumps({"type": "assistant", "cwd": "/", "message": {"content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "rm x"}}]}}, separators=(",", ":")) + "\n"),)),
]


# ===========================================================================
# The context hook
# ===========================================================================


def context(name: str, event: dict, text: str = "", /, **options: object) -> Case:  # keys are data
    options.setdefault("config", {})

    return Case(name, ("context.py",), event, False, text, **options)


CONTEXT_CASES = [
    context("a sub-agent is told no clock limits it", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "No clock limits you"),
    context("a sub-agent is told what stands in for Grep", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "use `rg` and `find`"),
    context("a session is told what stands in for Grep", {"hook_event_name": "SessionStart"}, "use `rg` and `find`"),
    context("a zsh user's agent is told the shell", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "The shell is zsh"),
    context("another shell is not called zsh", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, lacks="The shell is zsh", shell="/bin/bash"),
    context("the scratch folder is named", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "Throwaway files go in `scratch/`", config={"guard": {"scratch": "scratch"}}),
    context("no scratch folder, no line", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, lacks="Throwaway"),
    context("the temporary folder rule is named", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "A write under `/tmp` is refused", config={"guard": {"no_tmp": True}}),
    context("no temporary folder rule, no line", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, lacks="/tmp"),
    context("a session start names the orchestrator", {"hook_event_name": "SessionStart"}, "harness:orchestrator"),
    context("a session start's output is hook-specific", {"hook_event_name": "SessionStart"}, '"hookEventName": "SessionStart"'),
    context("a worker is told the full form", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "full form"),
    context("a scout is told the short form", {"hook_event_name": "SubagentStart", "agent_type": "harness:scout"}, "short form"),
    context("a bare runner is told the short form", {"hook_event_name": "SubagentStart", "agent_type": "runner"}, "short form"),
    context(
        "report.short tells a project's role",
        {"hook_event_name": "SubagentStart", "agent_type": "custom"},
        "short form",
        config={"report": {"short": ["custom"]}},
    ),
    context("a helper owes no report form", {"hook_event_name": "SubagentStart", "agent_type": "Explore"}, lacks="form"),
    context("a session start states the tool-turn rule", {"hook_event_name": "SessionStart"}, "few tool turns"),
    context("a worker is told the tool-turn rule", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "few tool turns"),
    context("a helper is told the tool-turn rule", {"hook_event_name": "SubagentStart", "agent_type": "Explore"}, "few tool turns"),
    context("no project means no context", {"hook_event_name": "SessionStart"}, lacks="orchestrator", config=None),
    context("the project variable finds the project", {"hook_event_name": "SessionStart"}, "orchestrator", cwd="elsewhere", project_dir="project"),
]


# ===========================================================================
# Runners
# ===========================================================================


# learning loop
RESET = (("turn.py", "reset"), {"session_id": SESSION})
HANDLED_AGENTS = (HANDLED_NAME, "deadbeef: rule written in AGENTS.md\n")


def handled_turn(name: str, handled: str, blocks: bool, text: str = "", /, *, rewrite: str = "", files: tuple[tuple[str, str], ...] = ()) -> Case:
    """A turn with one open inbox id and one handled line, a reset first, and AGENTS.md rewritten when `rewrite` is set."""

    before = (RESET, (("rewrite.py",), {"path": "AGENTS.md", "text": rewrite})) if rewrite else (RESET,)

    return turn(name, PROGRESS, blocks, text, files=(INBOX, (HANDLED_NAME, handled), RULE_FILE_BEFORE, *files), before=before)


def inbox_line(item_id: str, role: str, text: str, /) -> str:
    return f"- id={item_id} session=other agent={role} {text}\n"


def ledger(count: int, stamp: str, /, *, project: str = f"{ROOT}/project") -> tuple[str, str]:
    rows = "".join(json.dumps({"time": stamp, "project": project, "role": "worker"}) + "\n" for _ in range(count))

    return ("data/ledger.jsonl", rows)


OLD_TIME = "2000-01-01T00:00:00+0000"
NEW_TIME = "2099-01-01T00:00:00+0000"
SUB_WORKER = {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}
LESSON_FILES = (
    (INBOX_NAME, inbox_line("aaaaaaa1", "worker", "check the unit twice") + inbox_line("aaaaaaa2", "scout", "scout only text")),
    (HANDLED_NAME, "aaaaaaa1: rule written in AGENTS.md.\naaaaaaa2: rule written in AGENTS.md\n"),
    ("AGENTS.md", "a rule\n"),
)
def lessons(padding: int, /) -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
    """Six handled lessons of the worker, entry1 oldest, each padded to `padding` characters."""

    return (
        (INBOX_NAME, "".join(inbox_line(f"bbbbbbb{n}", "worker", f"entry{n} " + "x" * padding) for n in range(1, 7))),
        (HANDLED_NAME, "".join(f"bbbbbbb{n}: rule written in AGENTS.md\n" for n in range(1, 7))),
        ("AGENTS.md", "a rule\n"),
    )


def auto_lesson_files() -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
    """One handled worker lesson whose inbox text is an auto item."""

    return (
        (INBOX_NAME, inbox_line("aaaaaaa1", "worker", "[auto] DECIDE: pick one")),
        LESSON_FILES[1],
        LESSON_FILES[2],
    )


LOOP_CASES = [
    handled_turn("loop: a rule line with an unchanged file is refused", HANDLED_AGENTS[1], True, "was not changed"),
    handled_turn("loop: a rule line with a changed file is allowed", HANDLED_AGENTS[1], False, rewrite="a new rule\n"),
    handled_turn("loop: a rule line with a missing file is refused", "deadbeef: rule written in nope.md\n", True, "does not exist"),
    handled_turn("loop: a rule line naming no file is refused", "deadbeef: rule written in\n", True, "names no file"),
    handled_turn("loop: a file outside the rule paths is refused", "deadbeef: rule written in notes.md\n", True, "no rule file", files=(("notes.md", "n\n"),)),
    handled_turn("loop: a file outside the project needs only to exist", f"deadbeef: rule written in {ROOT}/outside.md\n", False, files=(("data/../outside.md", "o\n"),)),
    handled_turn("loop: a closing period after the file is ignored", "deadbeef: rule written in AGENTS.md.\n", False, rewrite="a new rule\n"),
    handled_turn("loop: a one-word rejection is refused", "deadbeef: rejected: no\n", True, "at least 3 words"),
    handled_turn("loop: an empty rejection is refused", "deadbeef: rejected:\n", True, "at least 3 words"),
    handled_turn("loop: a three-word rejection is allowed", "deadbeef: rejected: not a rule\n", False),
    context("loop: a worker is told the role's handled lessons", SUB_WORKER, "- (rule in AGENTS.md) check the unit twice", files=LESSON_FILES),
    context("loop: the lessons carry the already-acted header", SUB_WORKER, "do not redo the request:\\n- (rule in AGENTS.md)", files=LESSON_FILES),
    context("loop: a lesson whose rule file is gone is skipped", SUB_WORKER, lacks="check the unit twice", files=(LESSON_FILES[0], (HANDLED_NAME, "aaaaaaa1: rule written in gone.md\n"))),
    context("loop: an auto lesson is skipped", SUB_WORKER, "full form", lacks="pick one", files=auto_lesson_files()),
    context("loop: a lesson text is cut to 140 characters", SUB_WORKER, "entry6 " + "x" * 133, lacks="x" * 134, files=lessons(300)),
    context("loop: another role's lesson is not told", SUB_WORKER, lacks="scout only", files=LESSON_FILES),
    context("loop: a rejected lesson is not told", SUB_WORKER, lacks="Past feedback", files=(LESSON_FILES[0], (HANDLED_NAME, "aaaaaaa1: rejected: not a rule\n"))),
    context("loop: only the last five lessons are told", SUB_WORKER, "entry6", lacks="entry1", files=lessons(5)),
    context("loop: the lessons stay within 600 characters", SUB_WORKER, "entry6", lacks="entry2", files=lessons(100)),
    context("loop: an inbox with no handled file is no crash", SUB_WORKER, "full form", lacks="Past feedback", files=(LESSON_FILES[0],)),
    context("loop: a handled file with no inbox is no crash", SUB_WORKER, "full form", lacks="Past feedback", files=(LESSON_FILES[1],)),
    context("loop: ten new reports ask for a retro", {"hook_event_name": "SessionStart"}, "10 reports since the last retro: run harness:retro.", files=(ledger(10, OLD_TIME),)),
    context("loop: nine reports ask for nothing", {"hook_event_name": "SessionStart"}, lacks="retro", files=(ledger(9, OLD_TIME),)),
    context("loop: another project's reports do not count", {"hook_event_name": "SessionStart"}, lacks="retro", files=(ledger(10, OLD_TIME, project="/elsewhere"),)),
    context("loop: reports older than the marker do not count", {"hook_event_name": "SessionStart"}, lacks="retro", files=(ledger(10, OLD_TIME), ("data/retro-marker", ""))),
    context("loop: reports newer than the marker count", {"hook_event_name": "SessionStart"}, "12 reports since", files=(ledger(12, NEW_TIME), ("data/retro-marker", ""))),
    context("loop: the retro line keeps the orchestrator line", {"hook_event_name": "SessionStart"}, "harness:orchestrator", files=(ledger(10, OLD_TIME),)),
    context("loop: a subagent start gets no retro line", SUB_WORKER, lacks="retro", files=(ledger(10, OLD_TIME),)),
]


# skill gate


def skill_call(skill: str, /) -> dict:  # keys are data
    return assistant({"type": "tool_use", "id": f"t-{skill}", "name": "Skill", "input": {"skill": skill}})


def skill_lines(*skills: str) -> str:
    return "".join(json.dumps(skill_call(skill)) + "\n" for skill in skills)


def skill_gate(name: str, path: str, blocks: bool, text: str = "", /, *, agent: str = "", main: tuple[str, ...] = (), **options: object) -> Case:  # keys are data
    """An edit of `path`; `main` are the skills the session's transcript holds, `agent` the sub-agent's (a sub-agent call when set)."""

    gate_config = {"guard": {"scratch": "scratch"}, "skill_gate": {"*.py": ["harness:code-python"], "*.css": ["harness:code-html-css"], "docs/*.md": ["write-docs"], "*.md": ["write-md"]}}
    options.setdefault("config", gate_config)
    event = {"tool_name": "Edit", "tool_input": {"file_path": path}, "transcript_path": "transcript.jsonl"}
    if agent:
        event |= {"agent_id": "a1", "transcript_path": "project/s.jsonl"}
        options["files"] = (("s/subagents/agent-a1.jsonl", agent),)
    options.setdefault("transcript", tuple(skill_call(skill) for skill in main))
    event |= options.pop("event", {})

    return Case(name, ("skill_gate.py",), event, blocks, text, **options)


SKILL_GATE_CASES = [
    skill_gate("skill gate: an edit with the skill missing is refused", "app.py", True, "Load the skill harness:code-python with the Skill tool before editing app.py, then repeat the edit."),
    skill_gate("skill gate: a prefixed Skill call allows", "app.py", False, main=("harness:code-python",)),
    skill_gate("skill gate: a bare Skill call allows", "app.py", False, main=("code-python",)),
    skill_gate("skill gate: another skill does not allow", "app.py", True, main=("code-js",)),
    skill_gate(
        "skill gate: another tool naming a skill does not allow",
        "app.py",
        True,
        transcript=(assistant({"type": "text", "text": "Skill"}, {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"skill": "harness:code-python"}}),),
    ),
    skill_gate("skill gate: no key means no rule", "app.py", False, config={}),
    skill_gate("skill gate: no project means no rule", "app.py", False, config=None),
    skill_gate("skill gate: scratch is exempt", "scratch/t/x.py", False),
    skill_gate("skill gate: an unmatched extension passes", "notes.txt", False),
    skill_gate("skill gate: a path outside the project passes", "@ROOT@/elsewhere/app.py", False),
    skill_gate("skill gate: a nested file matches a bare pattern", "pkg/deep/app.py", True, "pkg/deep/app.py"),
    skill_gate("skill gate: a missing transcript lets the call run", "app.py", False, event={"transcript_path": "missing.jsonl"}),
    skill_gate("skill gate: a broken config lets the call run", "app.py", False, config={"skill_gate": ["not", "a map"]}),
    skill_gate("skill gate: a sub-agent reads its own transcript", "app.py", False, agent=skill_lines("harness:code-python")),
    skill_gate("skill gate: a sub-agent does not borrow the session's skill", "app.py", True, "harness:code-python", agent=skill_lines("code-js"), main=("harness:code-python",)),
    skill_gate("skill gate: the main session with an empty transcript is refused", "app.py", True, "harness:code-python"),
    skill_gate("skill gate: a preloaded skill counts", "app.py", False, agent=json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "<command-message>code-python</command-message>\n<command-name>harness:code-python</command-name>"}]}}) + "\n"),
    skill_gate("skill gate: a slash pattern beats a bare one", "docs/a.md", True, "write-docs"),
    skill_gate("skill gate: the winning pattern's skills are enough", "docs/a.md", False, main=("write-docs",)),
    skill_gate("skill gate: a bare pattern applies outside the slash one", "a.md", True, "write-md"),
    skill_gate("skill gate: every matching bare pattern is required", "app.py", True, "harness:code-html-css", config={"skill_gate": {"*.py": ["harness:code-python"], "app.*": ["harness:code-html-css"]}}, main=("code-python",)),
    skill_gate("skill gate: the union is allowed when both are loaded", "app.py", False, config={"skill_gate": {"*.py": ["harness:code-python"], "app.*": ["harness:code-html-css"]}}, main=("code-python", "harness:code-html-css")),
    skill_gate("skill gate: one line per missing skill", "app.py", True, "harness:code-html-css", config={"skill_gate": {"*.py": ["harness:code-python", "harness:code-html-css"]}}, main=("code-python",)),
]


def resolve(root: Path, name: str, /) -> Path:
    """A case's file: under the data folder when its name starts with `data/`, else under the project."""

    return root / "data" / name[5:] if name.startswith("data/") else root / "project" / name


def is_blocked(run: subprocess.CompletedProcess[str], /) -> bool:
    """Whether a hook blocked: exit 2, or the JSON decision on its stdout."""

    if run.returncode == 2:
        return True
    try:
        return json.loads(run.stdout).get("decision") == "block"
    except ValueError:
        return False


def check_files(case: Case, root: Path, /) -> str:
    if case.wrote is not None:
        path = resolve(root, case.wrote[0])
        if not path.exists() or case.wrote[1] not in path.read_text():
            return f"{case.wrote[0]} lacks {case.wrote[1]!r}"
    if case.not_wrote is not None:
        path = resolve(root, case.not_wrote[0])
        if path.exists() and case.not_wrote[1] in path.read_text():
            return f"{case.not_wrote[0]} holds {case.not_wrote[1]!r}"

    return ""


def run_hook(hooks: Path, script: tuple[str, ...], event: dict, environment: dict[str, str], root: Path, /) -> subprocess.CompletedProcess[str]:  # keys are data
    """Runs one hook on one event, the transcript paths of the event taken from the case's folder."""

    paths = {key: str(root / event[key]) for key in ("transcript_path", "agent_transcript_path") if key in event}

    return subprocess.run(
        ["uv", "run", "--script", str(hooks / script[0]), *script[1:]],
        input=json.dumps({**event, **paths}).replace(ROOT, str(root)),
        capture_output=True,
        text=True,
        env=environment,
        timeout=HOOK_TIMEOUT,
    )


def run_case(case: Case, hooks: Path, /) -> str:
    """Runs one case; returns the reason it failed, or an empty string."""

    WORK.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK) as directory:
        root = Path(directory).resolve()
        project = root / "project"
        (project / "scratch" / "t").mkdir(parents=True)
        (root / "data").mkdir()
        (project / "AGENTS.md").write_text("rules\n")
        if case.config is not None:
            (project / ".harness.json").write_text(json.dumps(case.config))
        for name, text in case.files:
            path = resolve(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text.replace(ROOT, str(root)))
        for name, target in case.links:
            (root / name).symlink_to(root / target)
        for name in (case.cwd, case.project_dir):
            if name:
                (root / name).mkdir(parents=True, exist_ok=True)
        (root / "transcript.jsonl").write_text("".join(f"{json.dumps(line)}\n" for line in case.transcript).replace(ROOT, str(root)))
        environment = {**os.environ, "CLAUDE_PLUGIN_DATA": str(root / "data"), "HOME": str(root), "UV_CACHE_DIR": UV_CACHE}
        environment.pop("CLAUDE_PROJECT_DIR", None)
        environment["SHELL"] = case.shell
        if case.project_dir:
            environment["CLAUDE_PROJECT_DIR"] = str(root / case.project_dir)
        for script, event in case.before:
            if script == ("rewrite.py",):
                (project / event["path"]).write_text(event["text"])
            else:
                run_hook(hooks, script, {"cwd": str(root / case.cwd), **event}, environment, root)
        run = run_hook(hooks, case.script, {"cwd": str(root / case.cwd), **case.event}, environment, root)
        message = run.stderr + run.stdout
        if case.is_exit_one:
            if run.returncode != 1:
                return f"expected exit 1, got {run.returncode}"
        elif run.returncode not in (0, 2):
            return f"the hook crashed, exit {run.returncode}: {message.strip()[-300:]!r}"
        elif is_blocked(run) != case.blocks:
            return f"expected blocks={case.blocks}, got {is_blocked(run)}: {message.strip()[:200]!r}"
        if case.text and case.text not in message:
            return f"the message lacks {case.text!r}: {message.strip()[:200]!r}"
        if case.lacks and case.lacks in message:
            return f"the message holds {case.lacks!r}: {message.strip()[:200]!r}"

        return check_files(case, root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default="", help="run the cases whose name holds this text")
    parser.add_argument("--hooks", type=Path, default=HOOKS, help="the hooks folder to judge")
    parser.add_argument("--fail-fast", action="store_true", help="stop at the first failure, for the bug-planting tools")
    parser.add_argument("--first", default="", help="run the cases of this hook first")
    parser.add_argument("--threads", type=int, default=JOBS, help="cases at once")
    arguments = parser.parse_args()
    every = [*GUARD_CASES, *GATE_CASES, *TURN_CASES, *DELEGATE_CASES, *BRIEF_CASES, *BUDGET_CASES, *SKILL_GATE_CASES, *NUDGE_CASES, *TOOL_CASES, *CONTEXT_CASES, *LOOP_CASES]
    cases = [case for case in every if arguments.only in case.name]
    cases.sort(key=lambda case: arguments.first not in case.script)
    failures = 0
    with ThreadPoolExecutor(arguments.threads) as pool:
        for case, reason in zip(cases, pool.map(lambda case: run_case(case, arguments.hooks), cases)):
            failures += bool(reason)
            print(f"FAIL {case.name}: {reason}" if reason else f"ok   {case.name}", flush=True)
            if reason and arguments.fail_fast:
                pool.shutdown(wait=False, cancel_futures=True)
                break
    print(f"{len(cases)} cases, {failures} failed")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

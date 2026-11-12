#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import argparse
import json
import os
import pwd
import shlex
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
HOOK_TIMEOUT = 10
JOBS = 8
ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
WORK = ACCOUNT_HOME / ".cache" / "harness-cases"
SESSION = "case-session"
ROOT = "@ROOT@"
STRICT = {
    "guard": {
        "scratch": "__scratch__",
        "deny_packages": True,
    },
}
NO_ASKING = {"guard": {"ask_packages": False}}
NO_DELAY = {"guard": {"tool_delay_days": 0}}
WEEK_AGO = (datetime.now(UTC).date() - timedelta(days=7)).isoformat()
OWNER_PROJECT_ENTRY = ("data/user.json", json.dumps({"projects": {ROOT + "/project": NO_ASKING}}))
GIT_MARK = (".git/HEAD", "ref: refs/heads/main\n")
GIT_IDENTITY = {"GIT_AUTHOR_NAME": "case", "GIT_AUTHOR_EMAIL": "case@localhost", "GIT_COMMITTER_NAME": "case", "GIT_COMMITTER_EMAIL": "case@localhost"}
BUSY_CALLS = ("Agent", "Edit", "Edit")
FULL_STATUS = "\n".join(f"## {heading}\nnothing" for heading in ("Verdict", "Done", "Needs you", "Next"))
PROGRESS = "Progress: two files are written, the third agent is still running."
OLD_CARD = (
    "| Score | Value | Why |\n| --- | --- | --- |\n| Task | 5/5 | done |\n| Brief | 4/5 | clear |\n| Ease | 5 | easy |\n\n"
    "**What would have helped:** nothing\n\n**How I would do it again:** the same"
)
OLD_REPORT = f"## Answer\nDone.\n## REPORT CARD\n{OLD_CARD}"
REPORT_SECTIONS = (
    ("Answer", "Changed one file."),
    ("Not proven", "- nothing was left unrun, every check ran"),
    ("Problems", "no problem met: the work ran as planned"),
    ("Next time", "The same order of work."),
    ("Open", "none"),
    ("Feedback", "none"),
    ("Verdict", "done: the unit is complete"),
)
REQUIRED_HEADINGS = ("Answer", "Not proven", "Verdict")
OPTIONAL_HEADINGS = ("Problems", "Next time", "Open", "Feedback")
AGENT_TYPES = ("harness:worker", "harness:scout", "harness:planner", "harness:reviewer", "harness:designer", "Explore", "custom")
HARNESS_AGENTS = ("harness:worker", "harness:scout", "harness:planner", "harness:reviewer", "harness:designer", "harness:researcher")


def build_report(sections: list[tuple[str, str]], /) -> str:
    return "\n".join(f"## {heading}\n{body}" for heading, body in sections)


def make_report(
    *, skip: str = "", headings: tuple[str, ...] = (), replace: tuple[str, str] = ("", ""), fill: dict[str, str] | None = None
) -> str:

    bodies = {replace[0]: replace[1], **(fill or {})}
    sections = [(heading, bodies.get(heading, body)) for heading, body in REPORT_SECTIONS]

    return build_report([(heading, body) for heading, body in sections if heading != skip and (not headings or heading in headings)])


def reorder_report(*headings: str) -> str:

    bodies = dict(REPORT_SECTIONS)

    return build_report([(heading, bodies[heading]) for heading in headings])


class Case(NamedTuple):

    name: str
    script: tuple[str, ...]
    event: dict
    blocks: bool
    text: str = ""
    config: dict | None = None
    files: tuple[tuple[str, str], ...] = ()
    wrote: tuple[str, str] | None = None
    not_wrote: tuple[str, str] | None = None
    transcript: tuple[dict, ...] = ()
    is_exit_one: bool = False
    plugin_root: str = ""
    lacks: str = ""
    cwd: str = "project"
    project_dir: str = ""
    links: tuple[tuple[str, str], ...] = ()
    before: tuple[tuple[tuple[str, ...], dict], ...] = ()
    shell: str = "/usr/bin/zsh"
    updated: dict | None = None
    is_unchanged: bool = False
    context: str = ""
    context_lacks: str = ""
    git: tuple[str, ...] = ()
    home: str = ""
    is_silent: bool = False
    start: str = ""
    max_seconds: float = 0.0




def bash(name: str, command: str, blocks: bool, text: str = "", /, *, config: dict | None = STRICT, **options: object) -> Case:
    event = {"tool_name": "Bash", "tool_input": {"command": command}}

    return Case(name, ("guard.py",), event, blocks, text, config, **options)


def agent_bash(name: str, command: str, blocks: bool, text: str = "", /, *, config: dict | None = None, **options: object) -> Case:
    event = {"tool_name": "Bash", "tool_input": {"command": command}, "agent_id": "agent-case1"}

    return Case(name, ("guard.py",), event, blocks, text, config, **options)


def background_bash(name: str, command: str, blocks: bool, text: str = "", /, **options: object) -> Case:
    event = {"tool_name": "Bash", "tool_input": {"command": command, "run_in_background": True}}

    return Case(name, ("guard.py",), event, blocks, text, STRICT, **options)


def write_call(name: str, path: str, blocks: bool, text: str = "", /, **options: object) -> Case:
    event = {"tool_name": "Write", "tool_input": {"file_path": path}}

    return Case(name, ("guard.py",), event, blocks, text, STRICT, **options)


def pattern(name: str, command: str, fixed: str, /, **options: object) -> Case:

    tool_input = {"command": command, "description": "d"}
    event = {"tool_name": "Bash", "tool_input": tool_input}

    return Case(name, ("guard.py",), event, False, "pattern position", STRICT, updated={**tool_input, "command": fixed}, **options)


PROJECT = f"{ROOT}/project"
SCRATCHPAD = f"/tmp/claude-{os.getuid()}/case-project/case-session/scratchpad"


def delay(name: str, command: str, fixed: str, /, *, text: str = "release delay", config: dict = STRICT, **options: object) -> Case:

    tool_input = {"command": command, "description": "d"}
    event = {"tool_name": "Bash", "tool_input": tool_input}

    return Case(name, ("guard.py",), event, False, text, config, updated={**tool_input, "command": fixed}, **options)


UV_CACHE = os.environ.get("UV_CACHE_DIR") or str(ACCOUNT_HOME / ".cache" / "uv")
HEREDOC = "python3 - <<'EOF'\nfrom pathlib import Path\n{call}\nEOF"
COMMIT = "git commit -m \"$(cat <<'EOF'\n{body}\nEOF\n)\""
DELETE = "Agents delete nothing."
AGENT_DELETE = "Sub-agents delete nothing."
HISTORY = "owner's to run"
ASK = '"permissionDecision": "ask"'
CLOUD = "writes to an AWS account"
INSTALLER = "runs code that nobody has read"
DBT_TEXT = "runs dbt against a target that is not a dev one"
SNOW_TEXT = "is the owner's to run or approve"
GLOB = "matches no file from"
REPO = "project files change"
SNOW_WRITE_FILES = (("write.sql", "create table t (a int);"), ("mixed.sql", "select 1;\n-- ok\ndelete from t;\n"))
SNOW_READ_FILES = (
    ("read.sql", "select 1;\nshow tables;\n"),
    ("comment.sql", "-- drop table t;\n/* delete from t; */\nselect 1;\n"),
    ("literal.sql", "select 'delete from t; drop table t';\n"),
)
GUARD_CASES = (
    bash("a package change asks the owner", "pip install x", True, '"permissionDecision": "ask"'),
    bash("a package change exits clean, so the call can run once accepted", "uv add x", True, "they are asked first", lacks="Blocked"),
    bash("the new key asks too", "pip install x", True, '"permissionDecision": "ask"', config={"guard": {"ask_packages": True}}),
    bash("an override turns the package question off", "pip install x", False, config={"guard": {"ask_packages": False}}),
    bash("the package question needs no project file", "pip install x", True, '"permissionDecision": "ask"', config=None),
    bash("the owner's file turns the package question off", "pip install x", False, config=None, files=(("data/user.json", '{"guard": {"ask_packages": false}}'),)),
    bash("the package question runs in the home folder", "pip install x", True, '"permissionDecision": "ask"', config=None, cwd=""),
    bash("the scratch rule is off in the home folder", "echo hi > AGENTS.md", False, config=None, cwd="", lacks=REPO),
    bash("rm in a root-level scratch folder is refused at the filesystem root", "rm /__scratch__/x.txt", True, DELETE, config=None, cwd="/"),
    bash("the scratch rule is off at the filesystem root", "echo hi > /etc/harness-case-x", False, config=None, cwd="/", lacks=REPO),
    bash("an override turns the scratch rule off", "echo hi > AGENTS.md", False, config={"guard": {"scratch": ""}}, lacks=REPO),
    bash("a /tmp write gets no note", "echo hi > /tmp/x", False, config=None, is_silent=True),
    bash("a write under the harness scratch folder gets no note", "echo hi > /tmp/harness/project/x", False, is_silent=True),
    bash("uvx asks the owner when the delay is off", "uvx ruff check src", True, '"permissionDecision": "ask"', config=NO_DELAY),
    bash("uv tool run asks the owner", "uv --quiet tool run ruff check src", True, '"permissionDecision": "ask"'),
    bash("uv tool install asks the owner", "uv tool install ruff", True, '"permissionDecision": "ask"'),
    bash("uv run of a pinned tool runs", "uv run --frozen ruff check src", False),
    bash("an override lets uvx run", "uvx ruff check src", False, config={"guard": {"ask_packages": False}}),
    bash("a package change beside a delete is refused outright", "pip install x; rm a", True, "Blocked by the harness guard", lacks="permissionDecision"),
    bash("a history rewrite is refused, not asked", "git push --force", True, "Blocked by the harness guard", lacks="permissionDecision"),
    bash("a bare uv run does not crash", "uv run", False),
    bash("a bare tar does not crash", "tar", False),
    bash("a quote in a quoted parameter opens nothing", """echo "${X:-it's}"; uv pip install y""", True),
    bash("a command after an ansi quote is still read", "echo $'a'; uv pip install y", True),
    bash("a command in a counted for loop is still read", "for ((i=0;i<1;i++)); do uv pip install y; done", True),
    bash("a bare bash -c does not crash", "bash -c", False),
    bash("a script named like a command is no command string", 'bash -x "pip install y"', False),
    bash("the words of a plain find run nothing", "find . pip install y", False),
    Case("a notebook under the temporary folder runs with no note", ("guard.py",), {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/tmp/n.ipynb"}}, False, config=STRICT, is_silent=True),
    bash("an escaped letter stays in its word", r"p\ip install x", True),
    bash("git with options alone passes", "git --version", False),
    bash("uv with options alone passes", "uv --version", False),
    bash("a positional parameter stays in a path", "echo a > /$1tmp/y", False),
    bash("a tar made under the temporary folder runs with no note", "tar -cf /tmp/a.tar b", False, is_silent=True),
    bash("a cd in a subshell does not move the next step", "(cd __scratch__); echo hi > AGENTS.md", False, REPO, is_unchanged=True),
    bash("an open backtick does not crash", "echo `ls", False),
    bash("a command after a parameter is still read", "echo ${X}; uv pip install y", True),
    bash("an open parameter does not crash", "echo ${X", False),
    bash("an in-place edit of a missing file is no write", "sed -i s/a/b/ /tmp/nope.txt", False),
    bash("rm is refused", "rm x", True, DELETE),
    bash("git clean is refused", "git clean -fd", True, DELETE),
    bash("a plain git push is allowed", "git push -u origin topic", False),
    bash("a failing glob is refused in zsh", "ls *.nothing", True, "matches no file"),
    bash("a failing glob passes when the shell is not zsh", "ls *.nothing", False, shell="/bin/bash"),
    bash("an option glob passes when the shell is not zsh", "grep -rn x --include=*.py .", False, shell="/bin/bash"),
    bash("no shell at all judges no glob", "ls *.nothing", False, shell=""),
    bash("a glob after a step that may write passes", "make && ls out/*.nothing", False),
    bash("a glob after a redirect passes", "echo hi > __scratch__/t/o.txt; cat __scratch__/t/o.*", False),
    bash("a glob after find -exec passes", "find . -name x -exec touch q1 \\; ; cat q*", False, config=None),
    bash("a glob after a read still fails", "echo hi; ls *.nothing", True, "matches no file"),
    pattern("an option glob after a step that may write is quoted", "make && grep -rn x --include=*.py .", "make && grep -rn x --include='*.py' ."),
    bash("a glob in bash -c passes", "bash -c 'ls *.nothing'", False),
    bash("an option glob in sh -c passes", "sh -c 'grep -rn x --include=*.py .'", False),
    bash("a glob in zsh -c is refused", "zsh -c 'ls *.nothing'", True, "matches no file"),
    bash("find from the root is refused", "find / -name tsc", True, "command -v tsc"),
    bash("find from the root with a pipe is refused", "find / -name tsc -path '*bin*' 2>/dev/null | head -3", True, "walks the entire disk"),
    bash("find from the home folder by tilde is refused", "find ~ -name x", True, "rg --files"),
    bash("find from HOME is refused", "find $HOME -type f", True),
    bash("find from quoted HOME is refused", 'find "$HOME" -name x', True),
    bash("find from a system folder is refused", "find /usr -name x", True),
    bash("find from a user's home folder is refused", "find /home/user -name x", True),
    bash("find from a second wide path is refused", "find . /etc -name x", True),
    bash("find from the root to depth four is refused", "find / -maxdepth 4 -name x", True),
    bash("find from the root with no depth after a flag is refused", "find -L / -name x", True),
    bash("find from the root to depth three passes", "find / -maxdepth 3 -name x", False),
    bash("find from a system folder to depth one passes", "find /usr -maxdepth 1", False),
    bash("find in the current folder passes", "find . -name x", False),
    bash("find in a deep project path passes", "find /home/user/proj -maxdepth 2", False),
    bash("find in a deep project path with no depth passes", "find /home/user/proj/src -name x", False),
    bash("find in a three-part project path with no depth passes", "find /home/user/proj -name x", False),
    bash("find by its path from the root is refused", "/usr/bin/find / -name x", True),
    bash("find in a variable folder passes", 'find "$dir" -name x', False),
    bash("find in a folder under home passes", "find ~/proj -name x", False),
    bash("find with no path passes", "find -name x", False),
    bash("find that names the root only in a pattern passes", "find . -path / -name x", False),
    bash("echo of a find passes", "echo find / -name x", False),
    bash("rg over the root files is refused", "rg --files /", True),
    bash("rg of a pattern over home is refused", "rg foo ~", True),
    bash("rg of a pattern over a project passes", "rg foo src", False),
    bash("rg with a slash pattern over a project passes", "rg / src", False),
    bash("rg files in a project with a glob passes", "rg --files -g '*.py'", False),
    bash("rg over home with a depth of two passes", "rg --max-depth 2 foo ~", False),
    bash("fd over the root is refused", "fd tsc /", True),
    bash("fd over the root with a depth of two passes", "fd -d 2 tsc /", False),
    bash("fd in the project passes", "fd tsc src", False),
    background_bash("a wide find in the background is refused too", "find / -name tsc", True),
    bash("a loop with no sleep passes", "while read line; do echo hi; done", False),
    bash("curl writing into the repo runs with a note", "curl -o AGENTS.md http://x", False, is_unchanged=True, context="let this run"),
    bash("curl with no output file passes", "curl http://x", False),
    bash("wget with no option writes into the repo, with a note", "wget http://x", False, is_unchanged=True, context="let this run"),
    bash("wget into a scratch folder passes", "wget -P __scratch__ http://x", False, lacks="let this run"),
    bash("wget -O into the repo runs with a note", "wget -O AGENTS.md http://x", False, is_unchanged=True, context="let this run"),
    bash("unlink is refused", "unlink x", True, DELETE),
    bash("find -delete is refused", "find . -name x -delete", True, DELETE),
    bash("find without -delete passes", "find . -name x", False),
    bash("rm after a pushd into scratch is refused", "pushd __scratch__ && rm x.txt", True, DELETE, config={"guard": {"scratch": "__scratch__"}}, files=(("__scratch__/x.txt", ""),)),
    bash("rm after a pushd into a project folder is refused", "pushd sub && rm -rf x", True, DELETE, config={"guard": {"scratch": "__scratch__"}}, files=(("sub/x", ""),)),
    bash("rm after a popd is judged from an unknown folder", "pushd __scratch__ && popd && rm x.txt", True, DELETE, config={"guard": {"scratch": "__scratch__"}}, files=(("__scratch__/x.txt", ""),)),
    bash("a copy into the repo runs with a note", "cp a AGENTS.md", False, is_unchanged=True),
    bash("a plain sed passes", "sed -n 1p AGENTS.md", False),
    bash("a sed -i in the repo runs with a note", "sed -i s/a/b/ AGENTS.md", False, is_unchanged=True),
    bash("an allowed uv command passes", "uv tree", False),
    bash("listing a tar writes nothing", "tar -tf a.tar", False),
    bash("cd past an option still knows its folder", "cd -P __scratch__/t && echo x > a.txt", False),
    bash("a <<- heredoc body is no command", "cat <<-EOF\nrm x\nEOF", False),
    bash("a forced git push is refused", "git push --force origin topic", True, "owner's to run"),
    bash("a +ref git push is refused", "git push origin +topic", True, "owner's to run"),
    bash("a delete git push is refused", "git push origin --delete topic", True, "owner's to run"),
    bash("git reset --hard is refused", "git reset --hard HEAD~1", True, "owner's to run"),
    bash("a broken owner's file keeps the hard rules", "git reset --hard HEAD~1", True, "owner's to run", config=None, files=(("data/user.json", "{bad"),)),
    bash("uv sync is refused", "uv sync", True, "owner's to run"),
    bash("an unquoted glob is refused", "ls *.py", True, GLOB),
    bash("a quoted glob is allowed", "ls '*.py'", False),
    pattern("an unquoted glob in an option is quoted", "grep --include=*.py x .", "grep --include='*.py' x ."),
    bash("a git clean dry run is allowed", "git clean -n", False),
    bash("a git clean long dry run is allowed", "git clean --dry-run -d", False),
    bash("a real git clean is refused", "git clean -fd", True, DELETE),
    bash("a config that is a list drops no rule", "git push --force origin main", True, "rewrites history", config=[]),
    bash("rm inside the scratch folder is refused", "rm __scratch__/x.txt", True, DELETE, config={"guard": {"scratch": "__scratch__"}}, files=(("__scratch__/x.txt", ""),)),
    bash("rm -rf of a folder inside scratch is refused", "rm -rf __scratch__/old", True, DELETE, config={"guard": {"scratch": "__scratch__"}}),
    bash("rm after a cd into scratch is refused", "cd __scratch__ && rm x.txt", True, DELETE, config={"guard": {"scratch": "__scratch__"}}, files=(("__scratch__/x.txt", ""),)),
    bash("rmdir inside the scratch folder is refused", "rmdir __scratch__/old", True, DELETE, config={"guard": {"scratch": "__scratch__"}}),
    bash("rm of the scratch folder itself is refused", "rm -rf __scratch__", True, DELETE, config={"guard": {"scratch": "__scratch__"}}),
    bash("rm out of scratch through dots is refused", "rm __scratch__/../a.txt", True, DELETE, config={"guard": {"scratch": "__scratch__"}}),
    bash("rm of a project file is refused with a scratch folder", "rm a.txt", True, DELETE, config={"guard": {"scratch": "__scratch__"}}),
    bash("rm beside a scratch path is refused", "rm __scratch__/x.txt a.txt", True, DELETE, config={"guard": {"scratch": "__scratch__"}}),
    bash("rm of a glob in scratch is refused", "rm __scratch__/*.txt", True, DELETE, config={"guard": {"scratch": "__scratch__"}}, files=(("__scratch__/x.txt", ""),)),
    bash("rm of an unset variable in scratch is refused", "rm __scratch__/$x", True, DELETE, config={"guard": {"scratch": "__scratch__"}}),
    bash("shred in scratch is refused", "shred __scratch__/x.txt", True, DELETE, config={"guard": {"scratch": "__scratch__"}}),
    bash("rm with the scratch folder turned off is refused", "rm __scratch__/x.txt", True, DELETE, config={"guard": {"scratch": ""}}),
    bash("a guard key that is null drops no rule", "git push --force origin main", True, "rewrites history", config={"guard": None}),
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
    pattern("a glob in an option from an unknown folder is quoted", "cd $x && grep --include=*.py x .", "cd $x && grep --include='*.py' x ."),
    bash("a glob that matches nothing gets no command to run instead", "ls *.nomatch", True, "`rg --files -g '*.nomatch'`", lacks="Run instead"),
    bash("the quoted fix of a failing glob passes", "ls '*.nomatch'", False),
    pattern("an option glob is quoted on its value", "rg foo --include=*.py", "rg foo --include='*.py'"),
    bash("of two globs that match nothing the first is named", "ls *.nomatch src/*.nope", True, "-g '*.nomatch'"),
    bash("the quoted fix of two failing globs passes", "ls '*.nomatch' 'src/*.nope'", False),
    bash("a glob word holding a quote is refused", "ls *.nomatch'x'", True, GLOB),
    pattern("find -name with a glob that matches is quoted", "find . -name *.py", "find . -name '*.py'", files=(("a.py", ""),)),
    pattern("rg -g with a glob that matches is quoted", "rg -g *.py x", "rg -g '*.py' x", files=(("a.py", ""),)),
    pattern("grep --include with a glob that matches is quoted", "grep --include *.py x .", "grep --include '*.py' x .", files=(("a.py", ""),)),
    bash("a matching glob after another command's -name is allowed", "ls -name *.py", False, files=(("a.py", ""),)),
    bash("$? is no glob", "echo $?", False),
    bash("a redirect over a project file runs with a note", "echo hi > AGENTS.md", False, REPO, is_unchanged=True),
    bash("a redirect into scratch is allowed", "echo hi > __scratch__/t/x.txt", False),
    bash("sed -i on a project file runs with a note", "sed -i s/a/b/ AGENTS.md", False, REPO, is_unchanged=True),
    bash("a repo write beside a delete is refused with the delete message only", "echo hi > AGENTS.md; rm x", True, DELETE, lacks="lets this call pass"),
    bash("python -c is not read as a shell", "python3 -c 'print(2 > 1)'", False),
    bash("a python heredoc is not read as a shell", HEREDOC.format(call="print(2 > 1)"), False),
    bash("a heredoc body is no command", "cat <<'EOF'\nrm x\nEOF", False),
    bash("a command after a heredoc is judged", "cat <<'EOF'\nx\nEOF\necho hi > AGENTS.md", False, REPO, is_unchanged=True),
    bash("a here-string word is no argument", "cat <<< a*b", False),
    bash("a soft git reset is allowed", "git reset --soft HEAD~1", False),
    bash("a plain git reset is allowed", "git reset HEAD~1", False),
    bash("git rm is allowed", "git rm -q __scratch__/x", False),
    bash("a project write inside bash -c runs with a note", "bash -c 'echo hi > AGENTS.md'", False, REPO, is_unchanged=True),
    write_call("a Write under /tmp runs with no note", "/tmp/x.txt", False, is_silent=True),
    write_call("a Write of a project file is allowed", "AGENTS.md", False),
    bash("rm is refused with no project", "rm x", True, DELETE, config=None),
    bash("a forced push is refused with no project", "git push -f", True, "owner's to run", config=None),
    bash("a glob is refused with no project", "ls *.py", True, GLOB, config=None),
    bash("a repo redirect is allowed with no project", "echo hi > AGENTS.md", False, config=None),
    bash("a /tmp redirect is allowed with no project", "echo hi > /tmp/x", False, config=None),
    bash("uv sync asks with no project file", "uv sync", True, '"permissionDecision": "ask"', config=None),
    bash("bare uv run python is allowed with no project", "uv run python x.py", False, config=None),
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
    *(bash(f"owner's git: {command!r}", command, True, f"`{label}` rewrites history", config=None) for command, label in (
        ("git checkout -- .", "git checkout <paths>"),
        ("git checkout .", "git checkout <paths>"),
        ("git checkout -f", "git checkout --force"),
        ("git checkout --forc main", "git checkout --force"),
        ("git switch -f main", "git switch --discard-changes"),
        ("git switch --discard-changes main", "git switch --discard-changes"),
        ("git restore .", "git restore"),
        ("git restore --staged --worktree a", "git restore"),
        ("git restore -SW a", "git restore"),
        ("git stash drop", "git stash drop"),
        ("git stash clear", "git stash clear"),
        ("git branch -D x", "git branch -D"),
        ("git branch -d --force x", "git branch -D"),
        ("git branch -df x", "git branch -D"),
        ("git branch -f main HEAD~1", "git branch --force"),
        ("git branch --force main HEAD~1", "git branch --force"),
        ("git branch -M main", "git branch --force"),
        ("git branch -C a b", "git branch --force"),
        ("git branch --copy --force a b", "git branch --force"),
        ("git checkout -B main", "git checkout -B"),
        ("git checkout -Bmain origin/main", "git checkout -B"),
        ("git switch -C main", "git switch --force-create"),
        ("git switch --force-create main", "git switch --force-create"),
        ("git read-tree --reset -u HEAD", "git read-tree --reset -u"),
        ("git read-tree -u --res HEAD", "git read-tree --reset -u"),
        ("git tag -d v1", "git tag --delete"),
        ("git tag --del v1", "git tag --delete"),
        ("git rebase main", "git rebase"),
        ("git pull --rebase", "git pull --rebase"),
        ("git pull -r origin main", "git pull --rebase"),
        ("git pull --rebase=interactive", "git pull --rebase"),
        ("git commit --amend -m x", "git commit --amend"),
        ("git commit --am -m x", "git commit --amend"),
        ("git filter-branch --all", "git filter-branch"),
        ("git filter-repo --force", "git filter-repo"),
        ("git reflog expire --expire=now --all", "git reflog expire"),
        ("git reflog delete HEAD@{1}", "git reflog delete"),
        ("git gc --prune=now", "git gc --prune"),
        ("git update-ref -d HEAD", "git update-ref -d"),
        ("git fetch -f origin main:main", "git fetch --force into a ref"),
        ("git fetch origin +main:main", "git fetch --force into a ref"),
        ("git worktree remove --force x", "git worktree remove --force"),
        ("git push --mirror", "git push --force"),
        ("git push --forc", "git push --force"),
        ("git push --del origin x", "git push --force"),
        ("git reset --ha HEAD~1", "git reset --hard"),
        ("git reset --h", "git reset --hard"),
        ("git -C . reset --hard", "git reset --hard"),
        ("env git rebase main", "git rebase"),
        ("command git stash drop", "git stash drop"),
        ("sudo -u root git checkout -- a", "git checkout <paths>"),
        ("bash -c 'git restore a'", "git restore"),
        ("find . -exec git checkout -- {} \\;", "git checkout <paths>"),
    )),
    bash("owner's git: a checkout of an existing file", "git checkout AGENTS.md", True, "`git checkout <paths>`", config=None, files=(("AGENTS.md", "x\n"),)),
    *(bash(f"kept git: {command!r}", command, False, config=None) for command in (
        "git checkout main",
        "git checkout -b fix",
        "git checkout -bfix",
        "git checkout -b fix origin/fix",
        "git switch -c new",
        "git switch main",
        "git restore --staged a.py",
        "git restore -S a.py",
        "git restore --staged --source=HEAD~1 a.py",
        "git stash",
        "git stash pop",
        "git stash list",
        "git branch -d x",
        "git branch -m old new",
        "git branch -c a b",
        "git branch -u origin/main",
        "git read-tree HEAD",
        "git read-tree --reset HEAD",
        "git read-tree -u -m HEAD",
        "git tag -a v1 -m msg",
        "git pull --no-rebase",
        "git pull --rebase=false",
        "git pull --ff-only",
        "git commit --allow-empty -m x",
        "git reflog",
        "git gc",
        "git gc --no-prune",
        "git fetch origin",
        "git fetch origin main:main",
        "git fetch -f origin",
        "git fetch origin '+refs/heads/*:refs/remotes/origin/*'",
        "git worktree remove x",
        "git push -u origin topic",
        "git push origin topic --",
        "git reset --soft HEAD~1",
        "git reset HEAD a.py",
        "rg 'git reset --hard' docs",
        "echo 'git checkout -- .'",
    )),
    *(bash(f"hidden: {command!r}", command, True, f"`{label}` runs where the guard cannot read", config=None) for command, label in (
        ("g=git; $g reset --hard", "git reset --hard"),
        ("G=git; ${G} reset --hard", "git reset --hard"),
        ("g=git; a='reset --hard'; $g $a", "git reset --hard"),
        ("$GIT stash drop", "git stash drop"),
        ("$(echo git) reset --hard", "git reset --hard"),
        ('bash -c "$(echo git reset --hard)"', "git reset --hard"),
        ('bash <<< "git reset --hard"', "git reset --hard"),
        ("bash <<'EOF'\ncd x && git stash drop\nEOF", "git stash drop"),
        ("echo 'git reset --hard' | sh", "git reset --hard"),
        ("python3 -c \"import os; os.system('git reset --hard')\"", "git reset --hard"),
        ("python3 -c \"import subprocess; subprocess.run(['git', 'checkout', '--', '.'])\"", "git checkout <paths>"),
        ("uv run python -c \"import os; os.system('git rebase main')\"", "git rebase"),
        ("bash -s <<EOF\nnpm install x\nEOF", "npm install x"),
        ("$PM add left-pad", "uv add left-pad"),
        ("python3 -c \"import os; os.system('npx tsc')\"", "npx tsc"),
        ("g=git; $(echo $g reset --hard)", "git reset --hard"),
    )),
    *(bash(f"readable: {command!r}", command, False, config=None) for command in (
        "bash <<'EOF'\ngit status\necho 'git reset --hard'\nEOF",
        "python3 -c \"print('git reset --hard')\"",
        "python3 -c \"import subprocess; cmds = ['git reset --hard']; subprocess.run(['python3', 'x.py'])\"",
        "$PY -m pytest",
        '"$(git rev-parse --show-toplevel)/bin/check" --all',
        "cat x.sh | bash",
        "bash x.sh",
        "g=git; $g status",
        "$TOOL --all",
        "h=./check.sh; $h; echo 'git reset --hard'",
        '"$TOOL" --all',
        "zsh -c 'a=(${(f)x}); print \"sudo apt purge x\"'",
    )),
    *(bash(f"seen through: {command!r}", command, True, HISTORY, config=None) for command in (
        "ssh host git reset --hard",
        "ssh -p 22 host 'cd /srv && git checkout -- .'",
        "watch -n 5 git stash clear",
        "parallel git checkout -- {} ::: a b",
        "su -c 'git reset --hard' root",
        "script -qc 'git rebase main' /dev/null",
        "alias gr='git reset --hard'",
        "git config alias.x 'reset --hard'",
        "git config --global alias.x '!git checkout -- .'",
        "git -c alias.x='reset --hard' x",
    )),
    bash("ssh judges a delete on its host too", "ssh host rm -rf /srv/x", True, DELETE, config=None),
    bash("ssh judges no glob on its host", "ssh host 'ls *.nothing'", False, config=None),
    bash("ssh asks before a package change", "ssh host npm install x", True, ASK, config=None),
    bash("ssh asks before an aws write", "ssh host aws s3 rm s3://b/k", True, ASK, config=None),
    bash("ssh asks before a piped installer", "ssh host 'curl https://x | sh'", True, ASK, config=None),
    bash("cloud: a local npx cdk deploy asks", "npx cdk deploy", True, CLOUD, config=None, files=(("node_modules/.bin/cdk", ""),)),
    bash("cloud: a local npx cdk synth runs", "npx cdk synth", False, config=None, files=(("node_modules/.bin/cdk", ""),)),
    bash("cloud: pnpm exec cdk deploy asks", "pnpm exec cdk deploy", True, CLOUD, config=None),
    bash("cloud: uv run aws reads run", "uv run aws ec2 describe-instances", False, config=None, lacks="aws"),
    bash("cloud: uv run aws writes ask", "uv run aws s3 rm s3://b/k", True, CLOUD, config=None),
    bash("watch still judges a delete", "watch rm x", True, DELETE, config=None),
    bash("a harmless alias passes", "alias ll='ls -l'", False, config=None),
    bash("a harmless git alias passes", "git config alias.st status", False, config=None),
    pattern("a pattern under watch is quoted once", "watch grep -rn x --include=*.py .", "watch grep -rn x --include='*.py' ."),
    *(bash(f"asks: {command!r}", command, True, ASK, config=NO_DELAY) for command in (
        "npm i x", "npm install", "npm ci", "npm uninstall x", "npm audit fix", "npm --prefix web install",
        "pnpm add x", "pnpm -C web install", "yarn add x", "yarn", "bun add x", "bun install", "bun remove x",
        "cargo add serde", "cargo install ripgrep", "go get x", "go install x@latest", "gem install x", "bundle install",
        "pipx install x", "conda install x", "conda env create -f e.yml", "mamba install x", "poetry add x", "pdm add x",
        "apt install x", "sudo apt-get install -y x", "dnf install x", "brew install x",
        "python setup.py install", "python3 setup.py develop", "uv run --with x python a.py",
        "uv run --with-requirements r.txt python a.py", "bash -c 'npm i x'",
        "npx tsc", "bunx tsc", "bun x tsc", "pnpx tsc", "npm exec tsc", "pnpm dlx create-vite", "yarn dlx tsc", "env npx tsc",
    )),
    *(bash(f"no ask: {command!r}", command, False, config=None) for command in (
        "npm run build", "npm test", "npm ls", "npm view x", "npm outdated", "npm audit", "npm explain x",
        "pnpm list", "pnpm why x", "yarn build", "yarn --version", "bun run x", "bun test", "pnpm run dlx", "yarn run dlx",
        "bun build x.ts", "cargo build", "cargo test", "go test ./...", "go build", "gem list", "pipx list", "conda list",
        "conda env list", "poetry show", "apt list --installed", "brew list", "python setup.py --version", "uv run python a.py",
    )),
    *(bash(f"local run passes: {command!r}", command, False, config=None, files=(("node_modules/.bin/tsc", ""),))
      for command in ("npx tsc", "npx --no-install tsc", "bunx tsc", "pnpx tsc", "bun x tsc", "pnpm dlx tsc", "yarn dlx tsc", "npm exec tsc", "npm exec -- tsc", "npm x tsc --noEmit")),
    *(bash(f"local run asks: {command!r}", command, True, ASK, config=NO_DELAY, files=(("node_modules/.bin/tsc", ""),))
      for command in ("npx tsc@5", "npx other", "npx -p tsc tsc", "npx -c tsc", "uvx tsc", "npx @scope/tsc", "npx ../tsc", "npm exec other", "pnpm dlx tsc@latest", "npm install tsc")),
    *(bash(f"cloud asks: {command!r}", command, True, CLOUD, config=None) for command in (
        "aws ec2 run-instances --image-id ami-1", "aws s3 rm s3://b/k", "aws s3 mb s3://b", "aws s3 rb s3://b", "aws s3 mv s3://a/k s3://b/k",
        "aws s3 cp f.txt s3://b/f.txt", "aws s3 sync . s3://b", "aws s3 cp s3://a/k s3://b/k", "aws lambda invoke --function-name f out.json",
        "aws dynamodb put-item --table-name t --item x", "aws iam create-user --user-name u", "aws cloudformation deploy --stack-name s",
        "aws configure set region eu-west-1", "aws configure", "aws sts assume-role --role-arn r --role-session-name s",
        "aws --profile p --region eu-west-1 --output json --no-cli-pager ec2 terminate-instances --instance-ids i-1",
        "aws --debug --endpoint-url http://x s3 rm s3://b/k", "aws ec2 --region r delete-volume --volume-id v",
        "sudo aws s3 rm s3://b/k", "env AWS_PROFILE=p aws ec2 stop-instances", "bash -c 'aws s3 rb s3://b'",
        "sam deploy --guided", "sam delete", "cdk watch", "cdk import", "sam publish", "sam pipeline bootstrap", "sam sync --stack-name s", "cdk deploy", "cdk destroy", "cdk bootstrap aws://1/eu-west-1",
        "aws s3 sync s3://b ./d && aws s3 rm s3://b/k",
    )),
    *(bash(f"cloud runs: {command!r}", command, False, config=None) for command in (
        "aws ec2 describe-instances", "aws iam list-users", "aws iam get-user", "aws ssm get-parameter --name n",
        "aws lambda batch-get-functions", "aws s3api head-object --bucket b --key k", "aws cloudtrail lookup-events",
        "aws quicksight search-dashboards --aws-account-id 1", "aws logs filter-log-events --log-group-name g", "aws ec2 wait instance-running --instance-ids i-1",
        "aws s3 ls", "aws s3 ls s3://b --recursive", "aws s3 cp s3://b/k ./k", "aws s3 cp s3://b/k -",
        "aws s3 sync s3://b ./d", "aws s3 sync s3://b ./d --exclude '*.tmp'", "aws sts get-caller-identity", "aws logs tail g --follow",
        "aws configure list", "aws configure list-profiles", "aws help", "aws --version", "aws", "aws ec2 help",
        "aws s3 cp help", "aws ec2 run-instances --help",
        "aws --profile p --region eu-west-1 --output json --no-cli-pager --debug ec2 describe-instances",
        "aws --endpoint-url http://x --profile p s3 ls", "aws ec2 --region r describe-volumes", "sudo aws iam list-users",
        "aws dynamodb query --table-name t", "aws dynamodb scan --table-name t", "aws cloudformation validate-template --template-body x", "aws resource-explorer-2 search --query-string q",
        "sam build", "sam validate", "sam local invoke f", "cdk synth", "cdk diff", "cdk ls", "sam deploy --help",
        "echo aws s3 rm s3://b/k", "grep aws README.md",
    )),
    bash("package question: the old key alone still asks", "pip install x", True, ASK, config={"guard": {"ask_packages": False, "deny_packages": True}}),
    delay("delay: uvx gets the delay first", "uvx ruff check src", "uvx '--exclude-newer=7 days' ruff check src"),
    delay("delay: uv tool run gets the delay after run", "uv tool run ruff check src", "uv tool run '--exclude-newer=7 days' ruff check src"),
    delay("delay: npx gets a date a week back", "npx tsc --noEmit", f"npx --before={WEEK_AGO} tsc --noEmit"),
    delay("delay: bunx gets seconds", "bunx tsc", "bunx --minimum-release-age=604800 tsc"),
    delay("delay: a scoped package is rewritten", "npx @scope/tool run", f"npx --before={WEEK_AGO} @scope/tool run"),
    delay("delay: a run in a chain is spliced in place", "cd sub && uvx ruff; echo done", "cd sub && uvx '--exclude-newer=7 days' ruff; echo done", files=(("sub/x", ""),)),
    delay("delay: a flag after the tool name does not count", "uvx ruff --exclude-newer 2020-01-01", "uvx '--exclude-newer=7 days' ruff --exclude-newer 2020-01-01"),
    delay("delay: uv run --with gets the delay after run", "uv run --with playwright python shot.py", "uv run '--exclude-newer=7 days' --with playwright python shot.py"),
    delay("delay: uv run --with= gets the delay after run", "uv run --with=pyyaml python a.py", "uv run '--exclude-newer=7 days' --with=pyyaml python a.py"),
    delay("delay: uv run --with-requirements gets the delay", "uv run --with-requirements r.txt python a.py", "uv run '--exclude-newer=7 days' --with-requirements r.txt python a.py"),
    delay("delay: uv run --with-editable gets the delay", "uv run --with-editable . python a.py", "uv run '--exclude-newer=7 days' --with-editable . python a.py"),
    delay("delay: uv run --frozen --with gets the delay", "uv run --frozen --with ruff ruff check", "uv run '--exclude-newer=7 days' --frozen --with ruff ruff check"),
    bash("delay: uv run with its own exclude-newer passes untouched", "uv run --exclude-newer '3 days' --with x python a.py", False, is_unchanged=True, lacks="release delay"),
    bash("delay: uv run with the equals form passes untouched", "uv run --with x --exclude-newer=2026-01-01 python a.py", False, is_unchanged=True, lacks="release delay"),
    delay("delay: a flag after the command is not uv's", "uv run --with x python a.py --exclude-newer 1", "uv run '--exclude-newer=7 days' --with x python a.py --exclude-newer 1"),
    bash("delay: plain uv run is untouched", "uv run python a.py", False, is_unchanged=True, lacks="release delay"),
    bash("delay: uv run --frozen without --with is untouched", "uv run --frozen ruff check src", False, is_unchanged=True, lacks="release delay"),
    bash("delay: uv run --with in a string asks", "bash -c 'uv run --with x python a.py'", True, ASK),
    bash("delay: uv run --with twice asks", "uv run --with x python a.py && uv run --with y python b.py", True, ASK),
    bash("delay: uv with a global option before run asks", "uv --quiet run --with x python a.py", True, ASK),
    bash("delay: uv run pip install still asks", "uv run pip install x", True, ASK),
    bash("delay: uv run after exclude-newer reads its value, so pip still asks", "uv run --exclude-newer '3 days' pip install x", True, ASK),
    bash("delay: uv run --with asks when the delay is off", "uv run --with x python a.py", True, ASK, config=NO_DELAY),
    delay("delay: the days come from the setting", "uvx ruff", "uvx '--exclude-newer=3 days' ruff", text="3-day release delay", config={"guard": {"deny_packages": True, "tool_delay_days": 3}}),
    bash("delay: a run twice in one command asks", "uvx ruff && uvx ruff", True, ASK),
    bash("delay: a run in a string asks", "bash -c 'uvx ruff'", True, ASK),
    bash("delay: a run beside a package change asks", "uvx ruff && pip install x", True, ASK),
    bash("delay: off asks again for npx", "npx tsc", True, ASK, config=NO_DELAY),
    bash("delay: a negative setting asks", "uvx ruff", True, ASK, config={"guard": {"deny_packages": True, "tool_delay_days": -1}}),
    bash("delay: uv tool install still asks", "uv tool install ruff", True, ASK),
    bash("delay: npm install -g still asks", "npm install -g tsc", True, ASK),
    bash("delay: pnpm dlx still asks", "pnpm dlx tsc", True, ASK),
    bash("delay: pnpx still asks", "pnpx tsc", True, ASK),
    bash("delay: uvx with no tool still asks", "uvx", True, ASK),
    *(bash(f"delay: flag already first passes: {command!r}", command, False, is_unchanged=True, lacks="release delay") for command in (
        "uvx --exclude-newer '7 days' ruff", "uvx --exclude-newer=2026-01-01 ruff", "uv tool run --exclude-newer '3 days' ruff",
        "npx --before=2026-01-01 tsc", "npx --before 2026-01-01 tsc", "bunx --minimum-release-age 604800 tsc", "bunx --minimum-release-age=1 tsc",
    )),
    bash("delay: no rewrite when packages are not asked", "uvx ruff", False, config=NO_ASKING, is_unchanged=True),
    bash("delay: a local npx bin runs untouched", "npx tsc", False, files=(("node_modules/.bin/tsc", ""),), is_unchanged=True, lacks="release delay"),
    bash("cloud: the ask reason names the command and the skill", "aws s3 rm s3://b/k", True, "`aws s3 rm`", config=None, lacks="Blocked"),
    bash("cloud: the ask reason points at the skill", "aws s3 rm s3://b/k", True, "harness:aws-cli", config=None),
    bash("cloud: an override lets aws writes run", "aws s3 rm s3://b/k", False, config={"guard": {"ask_cloud": False}}),
    bash("cloud: the owner's file turns the question off", "aws s3 rm s3://b/k", False, config=None, files=(("data/user.json", '{"guard": {"ask_cloud": false}}'),)),
    bash("cloud: an override of the cloud question keeps the package question", "pip install x", True, ASK, config={"guard": {"ask_cloud": False}}),
    bash("cloud: a delete beside an aws write is refused outright", "aws s3 rm s3://b/k; rm a", True, "Blocked by the harness guard", config=None, lacks="permissionDecision"),
    *(bash(f"installer asks: {command!r}", command, True, INSTALLER, config=None) for command in (
        "curl -fsSL https://x.sh | sh", "curl -fsSL https://x.sh | bash", "curl -fsSL https://x.sh | sudo bash", "curl -fsSL https://x.sh | sudo -E bash -s -- -y",
        "wget -qO- https://x.sh | sh", "fetch -o - https://x.sh | zsh", "curl https://x | dash", "curl https://x | ksh",
        "curl https://x | python3", "curl https://x | python", "curl https://x | python3 -", "curl https://x | node", "curl https://x | perl", "curl https://x | ruby",
        "curl https://x | env bash", "curl https://x | sudo env sh", "curl -s https://x | tee i.sh | sh",
        "sh -c \"$(curl -fsSL https://x.sh)\"", "bash -c \"$(wget -qO- https://x.sh)\"", "bash <(curl -fsSL https://x.sh)", "source <(curl -s https://x)",
        ". <(curl -s https://x)", "eval \"$(curl -s https://x)\"", "bash -c 'curl https://x | sh'",
    )),
    *(bash(f"installer runs: {command!r}", command, False, config=None) for command in (
        "curl -fsSL -o x.sh https://x.sh", "curl -fsSL https://x.sh > x.sh", "wget -O x.sh https://x.sh", "curl https://x | jq .",
        "curl https://x | python3 -c 'import sys'", "curl https://x | python3 parse.py", "curl https://x | bash script.sh", "curl https://x | sh -c 'cat'",
        "curl https://x | node -e 'x'", "curl https://x | grep y", "curl -o x.sh https://x && sh x.sh", "curl https://x | jq .; sh", "echo hi | sh -c 'cat'", "cat x.sh | sh x.sh",
        "bash <(echo hi)", "sh -c \"$(echo ls)\"", "x=$(curl https://x); python3 a.py", "curl https://x; sh a.sh",
    )),
    bash("installer: the ask reason names the pipe", "curl https://x | sh", True, "`curl ... | sh`", config=None, lacks="Blocked"),
    bash("installer: an override lets the pipe run", "curl https://x | sh", False, config={"guard": {"ask_installers": False}}),
    bash("installer: the owner's file turns the question off", "curl https://x | sh", False, config=None, files=(("data/user.json", '{"guard": {"ask_installers": false}}'),)),
    bash("installer: an override of the installer question keeps the cloud question", "aws s3 rm s3://b/k", True, CLOUD, config={"guard": {"ask_installers": False}}),
    bash("installer: a delete beside a pipe is refused outright", "curl https://x | sh; rm a", True, "Blocked by the harness guard", config=None, lacks="permissionDecision"),
    *(bash(f"dbt refuses: {command!r}", command, True, DBT_TEXT, config=None) for command in (
        "dbt run --target prod", "dbt build -t analytics_prod", "dbt run --target=prod", "dbt test --target ci", "dbt seed -t stage",
        "dbt snapshot --target prod", "dbt run-operation my_macro --target prod", "dbt retry -t prod", "dbt clone --target prod --state s",
        "dbt clone -t prod", "uv run dbt run --target prod", "uvx dbt run -t prod", "uvx --from dbt-snowflake dbt build --target prod",
        "poetry run dbt run --target prod", "python -m dbt run -t prod", "python3 -m dbt.cli.main run -t prod", "dbt --profiles-dir . run -t prod",
        "dbt run -t Prod", "dbt run --select my_model --target sandbox_prod", "DBT_TARGET=prod dbt run", "dbt run -t dev -t prod",
        "cd x && dbt run -t prod", "bash -c 'dbt run -t prod'", "dbt run -t device", "dbt run -t development",
    )),
    *(bash(f"dbt runs: {command!r}", command, False, config=None) for command in (
        "dbt run --target dev", "dbt run", "dbt build", "dbt run -t local", "dbt run -t sandbox", "dbt run -t dev_alice", "dbt run -t dev-alice",
        "dbt run --target=DEV", "dbt parse --target prod", "dbt compile -t prod", "dbt ls --target prod", "dbt debug -t prod", "dbt deps -t prod",
        "dbt docs generate -t prod", "uv run dbt parse -t prod", "dbt run --vars 'target: prod'", "echo dbt run -t prod", "grep 'dbt run -t prod' notes.md",
        "dbt run -t $TARGET", "uv run pytest -k dbt", "DBT_TARGET=dev dbt run", "dbt run --select prod_model", "dbt run -t dev --select prod",
    )),
    bash("dbt: the refusal names the target and the skill", "dbt run -t analytics_prod", True, "dbt run --target analytics_prod", config=None, lacks="permissionDecision"),
    bash("dbt: the refusal says how the owner gives the word", "dbt run -t prod", True, "guard.dbt_dev_targets", config=None),
    bash("dbt: a refusal is hard", "dbt run -t prod", True, "Blocked by the harness guard", config=None),
    bash("dbt: an override lets a non-dev target run", "dbt run -t prod", False, config={"guard": {"block_dbt_targets": False}}),
    bash("dbt: the owner's file lets a non-dev target run", "dbt run -t prod", False, config=None, files=(("data/user.json", '{"guard": {"block_dbt_targets": false}}'),)),
    bash("dbt: a target the owner lists is a dev one", "dbt run -t qa", False, config={"guard": {"dbt_dev_targets": ["qa"]}}),
    bash("dbt: a listed target is matched whatever its case", "dbt run -t QA", False, config={"guard": {"dbt_dev_targets": ["qa"]}}),
    bash("dbt: a listed target in capitals is matched", "dbt run -t qa", False, config={"guard": {"dbt_dev_targets": ["QA"]}}),
    bash("dbt: a listed target leaves the others refused", "dbt run -t prod", True, DBT_TEXT, config={"guard": {"dbt_dev_targets": ["qa"]}}),
    bash("dbt: turning it off keeps the other questions", "pip install x", True, ASK, config={"guard": {"block_dbt_targets": False}}),
    bash("dbt: a delete beside a refused dbt call is refused too", "dbt run -t prod; rm a", True, DELETE, config=None),
    *(bash(f"snow refuses: {command!r}", command, True, SNOW_TEXT, config=None, files=SNOW_WRITE_FILES) for command in (
        'snow sql -c dev -q "create table t (a int)"', 'snow sql -c dev -q "CREATE OR REPLACE VIEW v AS SELECT 1"', 'snow sql -c dev -q "drop table t"',
        'snow sql -c dev -q "truncate table t"', 'snow sql -c dev -q "delete from t"', 'snow sql -c dev -q "update t set a = 1"',
        'snow sql -c dev -q "insert into t values (1)"', 'snow sql -c dev -q "merge into t using s on 1=1 when matched then delete"',
        'snow sql -c dev -q "grant select on t to role r"', 'snow sql -c dev -q "revoke select on t from role r"', 'snow sql -c dev -q "call p()"',
        'snow sql -c dev -q "execute immediate \'select 1\'"', 'snow sql -c dev -q "put file:///x @s"', 'snow sql -c dev -q "remove @s/x"',
        'snow sql -c dev -q "copy into t from @s"', 'snow sql -c dev -q "undrop table t"', 'snow sql -c dev -q "select 1; drop table t"',
        'snow sql -c dev --query "create table t (a int)"', 'snow sql -c dev -q "-- note\ncreate table t (a int)"', 'snow sql -c dev -f write.sql',
        'snow sql -c dev --filename write.sql', 'snow sql -c dev -f mixed.sql', 'snow sql -c dev -f ./write.sql', "snow sql -c dev -q 'select 1' -q 'drop table t'",
        'snow sql -c dev -q "begin insert into t values (1); end"', 'snow object create table --json x -c dev', 'snow object drop table t -c dev',
        'snow app deploy -c dev', 'snow streamlit deploy -c dev', 'snow notebook deploy n -c dev', 'snow spcs image-repository drop r -c dev',
        'snow dbt deploy p -c dev', 'snow dbt execute p run -c dev', 'snow stage execute @s/x.sql -c dev', 'snow snowpark deploy -c dev',
        'snow stage copy ./f.txt @s -c dev', 'snow stage copy @a/f @b -c dev', 'snow stage remove @s/f -c dev', 'uv run snow app deploy -c dev', 'uvx snow sql -c dev -q "drop table t"',
        'cd x && snow sql -c dev -q "drop table t"', 'SNOWFLAKE_DEFAULT_CONNECTION_NAME=my_prod snow sql -q "select 1"',
    )),
    *(bash(f"snow production connection refuses: {command!r}", command, True, SNOW_TEXT, config=None, files=SNOW_READ_FILES) for command in (
        'snow sql -c prod -q "select 1"', 'snow sql --connection analytics_prod -q "select 1"', 'snow sql --connection=my_PROD -q "show tables"',
        'snow connection test -c prod', 'snow object list table -c production', 'snow sql -c prod_ro -f read.sql',
    )),
    *(bash(f"snow runs: {command!r}", command, False, config=None, files=SNOW_READ_FILES) for command in (
        'snow sql -c dev -q "select 1"', 'snow sql -c dev -q "SELECT * FROM t LIMIT 5"', 'snow sql -c dev -q "show tables"',
        'snow sql -c dev -q "describe table t"', 'snow sql -c dev -q "list @s"', 'snow sql -c dev -q "explain select 1"',
        'snow sql -c dev -q "use role r"', 'snow sql -c dev -q "alter session set query_tag = \'x\'"',
        'snow sql -c dev -q "select 1 -- drop table t"', 'snow sql -c dev -q "-- drop table t\nselect 1"',
        'snow sql -c dev -q "select 1 // delete from t"',
        'snow sql -c dev -q "select 1;\n// drop table t\nselect 2"', 'snow sql -c dev -q "select 1;\\n// drop table t"',
        'snow sql -c dev -q "select $$x; drop table t$$"', 'snow sql -c dev -q "select \\"a;drop\\" from t"', 'snow sql -c dev -q "/* drop table t */ select 1"',
        'snow sql -c dev -q "select \'drop table t\'"', 'snow sql -c dev -q "select \'it\'\'s; drop table t\'"',
        'snow sql -c dev -q "select \"drop\" from t"', 'snow sql -c dev -q "select $$delete from t$$"',
        'snow sql -c dev -q "select create_date, updated_at, insert_id from t"', 'snow sql -c dev -f read.sql', 'snow sql -c dev -f comment.sql',
        'snow sql -c dev -f literal.sql', 'snow sql -c dev -f missing.sql', 'snow sql -c dev -f .', 'snow sql -c dev -f $FILE', "snow sql -c dev -i",
        'snow sql -c my_dev -q "select 1"', 'snow sql -q "select 1"',
        'snow object list table -c dev', 'snow stage list @s -c dev', 'snow stage copy @s/f ./local -c dev', 'snow app run --help',
        'snow connection test -c dev', 'snow connection list', 'snow --help', 'snow app version list -c dev',
        'snow snowpark build', 'snow sql -c dev -q "select 1" --format json', 'echo snow sql -c prod', "grep 'snow app deploy' notes.md",
        'SNOWFLAKE_DEFAULT_CONNECTION_NAME=dev snow sql -q "select 1"', 'snow sql -c dev -q "begin transaction; select 1; commit"',
    )),
    bash("snow: a relative file after a cd to an unknown folder is not read", 'cd "$WORK" && snow sql -c dev -f write.sql', False, config=None, files=SNOW_WRITE_FILES, start="project"),
    bash("snow: the refusal names the statement and the skill", 'snow sql -c dev -q "drop table t"', True, "snow sql (DROP)", config=None),
    bash("snow: the refusal says to propose a file in scratch", 'snow sql -c dev -q "drop table t"', True, "/tmp/harness/<project>/", config=None),
    bash("snow: the refusal says how the owner allows it", 'snow sql -c dev -q "drop table t"', True, "guard.block_snow", config=None),
    bash("snow: the refusal names the production connection", 'snow sql -c prod -q "select 1"', True, "production connection prod", config=None),
    bash("snow: a refusal is hard", 'snow sql -c dev -q "drop table t"', True, "Blocked by the harness guard", config=None, lacks="permissionDecision"),
    bash("snow: an override lets a write run", 'snow sql -c dev -q "drop table t"', False, config={"guard": {"block_snow": False}}),
    bash("snow: an override lets a production read run", 'snow sql -c prod -q "select 1"', False, config={"guard": {"block_snow": False}}),
    bash("snow: the owner's file lets a write run", 'snow sql -c dev -q "drop table t"', False, config=None, files=(("data/user.json", '{"guard": {"block_snow": false}}'),)),
    bash("snow: turning it off keeps the dbt rule", "dbt run -t prod", True, DBT_TEXT, config={"guard": {"block_snow": False}}),
    bash("snow: a delete beside a refused snow call is refused too", 'snow app deploy -c dev; rm a', True, DELETE, config=None),
    agent_bash("agent: refused git commit -m x", "git commit -m x", True, "git commit"),
    agent_bash("agent: refused git push", "git push", True, "git push"),
    agent_bash("agent: refused git stash", "git stash", True, "git stash"),
    agent_bash("agent: refused git tag v1", "git tag v1", True, "git tag"),
    agent_bash("agent: refused git -C /x add f", "git -C /x add f", True, "git add"),
    agent_bash("agent: refused git -c user.name=a commit -m x", "git -c user.name=a commit -m x", True, "git commit"),
    agent_bash("agent: refused GIT_DIR=x git push origin main", "GIT_DIR=x git push origin main", True, "git push"),
    agent_bash("agent: refused sh -c 'git push'", "sh -c 'git push'", True, "git push"),
    agent_bash("agent: refused git status && git commit -m x", "git status && git commit -m x", True, "git commit"),
    agent_bash("agent: refused git log | head; git stash drop", "git log | head; git stash drop", True, "git stash"),
    agent_bash("agent: refused git fetch", "git fetch", True, "git fetch"),
    agent_bash("agent: refused git branch foo", "git branch foo", True, "git branch"),
    agent_bash("agent: refused git branch -m old new", "git branch -m old new", True, "git branch"),
    agent_bash("agent: refused git tag -d v1", "git tag -d v1", True, "git tag"),
    agent_bash("agent: refused git config user.name x", "git config user.name x", True, "git config"),
    agent_bash("agent: refused git config --unset user.name", "git config --unset user.name", True, "git config"),
    agent_bash("agent: refused git remote add o u", "git remote add o u", True, "git remote"),
    agent_bash("agent: refused git worktree add ../w", "git worktree add ../w", True, "git worktree"),
    agent_bash("agent: refused git stash push -m x", "git stash push -m x", True, "git stash"),
    agent_bash("agent: refused git diff --output=out.txt", "git diff --output=out.txt", True, "git diff"),
    agent_bash("agent: refused gh pr create --title t", "gh pr create --title t", True, "gh pr create"),
    agent_bash("agent: refused gh -R o/r pr merge 1", "gh -R o/r pr merge 1", True, "gh pr merge"),
    agent_bash("agent: refused gh issue comment 1 -b x", "gh issue comment 1 -b x", True, "gh issue comment"),
    agent_bash("agent: refused gh release delete v1", "gh release delete v1", True, "gh release delete"),
    agent_bash("agent: refused gh repo fork o/r", "gh repo fork o/r", True, "gh repo fork"),
    agent_bash("agent: refused gh api -X POST /x", "gh api -X POST /x", True, "gh api"),
    agent_bash("agent: refused gh api --method=DELETE /x", "gh api --method=DELETE /x", True, "gh api"),
    agent_bash("agent: refused gh api -XPATCH /x", "gh api -XPATCH /x", True, "gh api"),
    agent_bash("agent: refused gh api /x -f a=b", "gh api /x -f a=b", True, "gh api"),
    agent_bash("agent: refused gh api /x --input body.json", "gh api /x --input body.json", True, "gh api"),
    agent_bash("agent: runs git status", "git status", False),
    agent_bash("agent: runs git diff --stat", "git diff --stat", False),
    agent_bash("agent: runs git log -n 3", "git log -n 3", False),
    agent_bash("agent: runs git -C /x log -n 3", "git -C /x log -n 3", False),
    agent_bash("agent: runs git -c core.pager=cat show HEAD", "git -c core.pager=cat show HEAD", False),
    agent_bash("agent: runs git branch --list", "git branch --list", False),
    agent_bash("agent: runs git branch", "git branch", False),
    agent_bash("agent: runs git branch -a", "git branch -a", False),
    agent_bash("agent: runs git branch --contains abc", "git branch --contains abc", False),
    agent_bash("agent: runs git stash list", "git stash list", False),
    agent_bash("agent: runs git stash show -p", "git stash show -p", False),
    agent_bash("agent: runs git tag", "git tag", False),
    agent_bash("agent: runs git tag -l 'v*'", "git tag -l 'v*'", False),
    agent_bash("agent: runs git config --get user.name", "git config --get user.name", False),
    agent_bash("agent: runs git config --list", "git config --list", False),
    agent_bash("agent: runs git remote -v", "git remote -v", False),
    agent_bash("agent: runs git remote get-url origin", "git remote get-url origin", False),
    agent_bash("agent: runs git worktree list", "git worktree list", False),
    agent_bash("agent: runs git rev-parse HEAD", "git rev-parse HEAD", False),
    agent_bash("agent: runs git ls-files", "git ls-files", False),
    agent_bash("agent: runs git --version", "git --version", False),
    agent_bash("agent: runs git status && git diff | head", "git status && git diff | head", False),
    agent_bash("agent: runs gh pr view 1", "gh pr view 1", False),
    agent_bash("agent: runs gh pr list", "gh pr list", False),
    agent_bash("agent: runs gh pr diff 1", "gh pr diff 1", False),
    agent_bash("agent: runs gh pr checks 1", "gh pr checks 1", False),
    agent_bash("agent: runs gh issue view 1", "gh issue view 1", False),
    agent_bash("agent: runs gh run list", "gh run list", False),
    agent_bash("agent: runs gh api /repos/x", "gh api /repos/x", False),
    agent_bash("agent: runs gh api -X GET /repos/x", "gh api -X GET /repos/x", False),
    agent_bash("agent: refused git branch --list -d old", "git branch --list -d old", True, "git branch"),
    agent_bash("agent: refused git tag -l -a v1", "git tag -l -a v1", True, "git tag"),
    agent_bash("agent: refused git tag --list --delete v1", "git tag --list --delete v1", True, "git tag"),
    agent_bash("agent: runs gh api -X GET /x -f a=b", "gh api -X GET /x -f a=b", False),
    agent_bash("agent: refused git apply p.patch", "git apply p.patch", True, "git apply"),
    agent_bash("agent: refused git apply --index p.patch", "git apply --index p.patch", True, "git apply"),
    agent_bash("agent: runs git apply --check p.patch", "git apply --check p.patch", False),
    agent_bash("agent: runs git archive HEAD src", "git archive HEAD src", False),
    agent_bash("agent: runs git check-attr -a f", "git check-attr -a f", False),
    agent_bash("agent: runs git count-objects -v", "git count-objects -v", False),
    agent_bash("agent: the refusal tells the agent to report and leave the commit to the main session", "git commit -m x", True, "describe the change in your handback and the main session commits it"),
    agent_bash("agent: the refusal is hard", "git push", True, "Blocked by the harness guard", lacks="permissionDecision"),
    agent_bash("agent: the refusal names the smallest read form", "git branch foo", True, "`git branch --list`"),
    agent_bash("agent: a git write inside python is refused as hidden", "python3 -c \"import subprocess; subprocess.run(['git', 'commit', '-m', 'x'])\"", True, "git commit"),
    bash("agent: the main session may commit", "git commit -m x", False, config=None),
    bash("agent: the main session may push", "git push origin main", False, config=None),
    bash("agent: the main session may create a pull request", "gh pr create --title t", False, config=None),
    bash("agent: the main session may stash", "git stash", False, config=None),
    Case("agent: an empty agent_id is the main session", ("guard.py",), {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "agent_id": ""}, False, config=None),
    bash("a glob after [[ ]] is judged", "[[ -f x ]] && ls *.py", True, GLOB, config=None),
    bash("a glob after $(( )) is judged", "echo $((1 + 1)) *.py", True, GLOB, config=None),
    bash("strict: python3 -m pip is refused", "python3 -m pip install x", True, HISTORY),
    bash("strict: python -mpip is refused", "python -mpip install x", True, HISTORY),
    bash("strict: uv run pip is refused", "uv run pip install x", True, HISTORY),
    bash("strict: uv run python -m pip is refused", "uv run python -m pip install x", True, HISTORY),
    bash("strict: mv of a project file runs with a note", "mv AGENTS.md __scratch__/gone", False, REPO, is_unchanged=True),
    bash("strict: mv inside scratch is allowed", "mv __scratch__/a __scratch__/b", False),
    bash("strict: mv of a /tmp file into scratch is allowed", "mv /tmp/a __scratch__/b", False),
    bash("strict: cp out of the project tree into scratch is allowed", "cp AGENTS.md __scratch__/copy", False),
    bash("strict: cp -t names its destination", "cp -t . __scratch__/x", False, REPO, is_unchanged=True),
    bash("strict: cp -t into scratch is allowed", "cp -t __scratch__ AGENTS.md", False),
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
    bash("strict: a pipeline after a cd keeps the folder", "cd __scratch__ && make 2>&1 | tee out.log", False),
    bash("strict: a later command after a pipeline keeps the folder", "cd __scratch__ && echo a | cat && echo hi > ok.txt", False),
    bash("strict: a redirect at a pipeline's end keeps the folder", "cd __scratch__ && git log | head -3 > out.txt", False),
    bash("strict: a cd in a pipeline leaves the folder unknown", "cd __scratch__ | cat; echo hi > ok.txt", False, REPO, is_unchanged=True),
    bash("strict: a cd in the background leaves the folder unknown", "cd __scratch__ & echo hi > ok.txt", False, REPO, is_unchanged=True),
    bash("strict: a cd and its list in the background", "cd __scratch__ && echo a &\necho hi > ok.txt", False, REPO, is_unchanged=True),
    bash("strict: a cd in a substitution leaves the folder", "x=$(cd __scratch__); echo hi > AGENTS.md", False, REPO, is_unchanged=True),
    bash("strict: a command after a redirect target is no target", "echo a >&2; rm x", True, DELETE),
    bash("strict: a malformed redirect does not swallow the next command", "echo a > ; rm x", True, DELETE),
    bash("strict: a closed descriptor names no file", "echo a >&- b", False),
    bash("strict: a cd after an ended pipeline keeps its folder", "echo a | cat; cd __scratch__; echo hi > ok.txt", False),
    bash("an argument after a process substitution is no command", "diff <(sort a) rm", False, config=None),
    bash("strict: __scratch__/ is the scratch folder", "echo hi > __scratch__/x.txt", False, config={"guard": {"scratch": "__scratch__/"}}),
    bash("strict: ./scratch is the scratch folder", "echo hi > __scratch__/x.txt", False, config={"guard": {"scratch": "./__scratch__"}}),
    bash("strict: __scratch__/ still guards the rest", "echo hi > AGENTS.md", False, REPO, config={"guard": {"scratch": "__scratch__/"}}, is_unchanged=True),
    bash("strict: a symlinked cwd is still inside", "echo hi > AGENTS.md", False, REPO, cwd="link", links=(("link", "project"),), is_unchanged=True),
    bash("strict: a symlinked cwd still reaches __scratch__", "echo hi > __scratch__/x.txt", False, cwd="link", links=(("link", "project"),)),
    bash("strict: a symlink in scratch to the project is a project write", "echo hi > __scratch__/out/AGENTS.md", False, REPO, links=(("project/__scratch__/out", "project"),), is_unchanged=True),
    bash("the project variable pins the rules past a cd", "uv sync", True, HISTORY, cwd="elsewhere", project_dir="project"),
    bash("the project variable pins the writes too", "echo hi > ../project/AGENTS.md", False, REPO, cwd="elsewhere", project_dir="project", is_unchanged=True),
    bash("the project variable wins over a cwd's entry", "uv add x", True, "they are asked first", config=None, cwd="project", project_dir="elsewhere", files=(OWNER_PROJECT_ENTRY,)),
    bash("without the variable the walk goes up from cwd", "uv sync", True, HISTORY, cwd="project/__scratch__/t"),
    bash("without the variable a cwd outside takes no entry", "uv add x", True, "they are asked first", config=None, cwd="elsewhere", files=(OWNER_PROJECT_ENTRY,)),
    bash("a projects entry applies to its root", "uv add x", False, config=None, files=(OWNER_PROJECT_ENTRY,)),
    bash("a projects glob matches the root", "uv add x", False, config=None, files=(("data/user.json", json.dumps({"projects": {"@ROOT@/pro*": NO_ASKING}})),)),
    bash("a projects entry of another folder does not apply", "uv add x", True, "they are asked first", config=None, files=(("data/user.json", json.dumps({"projects": {"@ROOT@/other": NO_ASKING}})),)),
    bash("a folder below the git root takes the root's entry", "uv add x", False, config=None, cwd="project/sub", files=(OWNER_PROJECT_ENTRY, GIT_MARK)),
    bash("a repository kept in the home folder is no project root", "uv add x", False, config=None, cwd="project/sub", files=(("data/user.json", json.dumps({"projects": {ROOT + "/project/sub": NO_ASKING}})), ("../.git/HEAD", "ref: refs/heads/main\n"))),
    bash("with no git root the start folder is the project", "uv add x", True, "they are asked first", config=None, cwd="project/sub", files=(OWNER_PROJECT_ENTRY,)),
    pattern("a quoted pattern keeps every other input field", "find . -name *.txt -print", "find . -name '*.txt' -print"),
    bash("a pattern also in a heredoc body is refused", "cat <<'EOF'\n--include=*.py\nEOF\ngrep --include=*.py x .", True, "could not quote it safely"),
    bash("a pattern glob written with a quote is refused", "grep --include=*.p'y' x .", True, "could not quote it safely"),
    bash("a pattern beside a glob that matches nothing is refused for the glob", "ls *.nothing; find . -name *.py", True, "-g '*.nothing'", lacks="could not quote"),
    bash("a glob that matches nothing names its folder", "ls *.nothing", True, f"matches no file from {PROJECT}, so zsh fails", lacks="Run instead"),
    bash("the folder named is the one a cd reaches", "cd sub && ls *.py", True, f"from {PROJECT}/sub,", files=(("sub/b.txt", ""),)),
    bash("a glob that matches nothing names its pattern", "ls src/*.nope", True, "`rg --files -g 'src/*.nope'` or `git ls-files`"),
    *(bash(f"refused delete: {command!r}", command, True, DELETE, config=None) for command in (
        "rm -rf node_modules",
        "rm -rf web/node_modules/x",
        "rm -rf dist",
        "rm -rf .venv/lib",
        "rm .git/config",
        "rm -rf ../project",
        "rm -rf .",
        "rm /etc/hostname",
        "rm -rf ~",
        "rm -rf __harness__/trash/old",
        "rm -rf __harness__",
        "rm -f $x",
        "rm a a",
        "rm -rf sub sub/x",
        "rm -f a; cd sub && rm -f a",
        "rm -i a",
        "rm -rf --no-preserve-root a",
        "rmdir -p a/b",
        "cd $x && rm -f a",
        "sudo rm a",
        "command rm a",
        "/bin/rm a",
        "xargs rm < list",
        "bash -c 'rm a'",
        "find . -name a -exec rm {} +",
        "eval rm a",
        "LC_ALL=C rm a",
        "d=a && rm -f '$d'",
        'd=a; for d in b; do rm -f "$d"; done',
        'echo "x; rm -f a; y" && rm -f a',
        "cat <<'EOF'\nrm -f a\nEOF\nrm -f a\"\"",
    )),
    bash("rm of a glob is refused", "rm *.txt", True, DELETE, config=None, files=(("a.txt", ""),)),
    bash("rm in the home folder is refused", "rm -f a", True, DELETE, config=None, cwd=""),
    bash("a delete beside a package change is refused, not asked", "pip install x; rm -f a", True, DELETE, config=None, lacks="permissionDecision"),
    bash("rm of a project file is refused", "rm a.txt", True, DELETE, config=None, files=(("a.txt", "x"),)),
    bash("rm of a nested project file is refused", "rm src/a.py", True, DELETE, config=None, files=(("src/a.py", "x"),)),
    bash("rm -rf of a project folder is refused", "rm -rf build", True, DELETE, config=None),
    bash("rmdir of a project folder is refused", "rmdir old", True, DELETE, config=None),
    bash("a delete in a chain is refused", "make && rm -f out.txt && echo done", True, DELETE, config=None),
    bash("a delete with a variable set to a literal is refused", 'd=build && rm -rf "$d"', True, DELETE, config=None),
    bash("shred is refused", "shred x.txt", True, DELETE, config=None),
    bash("git clean is refused", "git clean -fd", True, DELETE, config=None),
    bash("the refusal names no trash folder and no rm in scratch", "rm a.txt", True, "a fresh run takes a new subfolder", config=None, lacks="__harness__/trash"),
    bash("rm of a scratch variable is refused", 'd=__scratch__/x && rm -rf "$d"', True, DELETE),
    bash("the fresh-run form of a scratch reset is refused", 'd=__scratch__/ctl && rm -rf "$d" && mkdir -p "$d"', True, DELETE),
    bash("rm -rf of a scratch path is refused", "rm -rf __scratch__/x", True, DELETE),
    bash("rmdir of a scratch folder is refused", "rmdir __scratch__/x", True, DELETE),
    bash("unlink of a scratch file is refused", "unlink __scratch__/x.txt", True, DELETE),
    bash("find -delete on scratch is refused", "find __scratch__ -delete", True, DELETE),
    bash("find -delete past an expression in scratch is refused", "find __scratch__/old -name '*.log' -delete", True, DELETE),
    bash("find in scratch with no delete passes", "find __scratch__ -name '*.log'", False),
    agent_bash("a sub-agent is refused an rm in scratch with its own message", "rm -rf __scratch__/x", True, AGENT_DELETE, config=STRICT, lacks="give the owner"),
    agent_bash("a sub-agent is refused a project rm with its own message", "rm a.txt", True, AGENT_DELETE, config=None, lacks="give the owner"),
    bash("the main session is told to give the owner the command", "rm a.txt", True, "give the owner the command in the chat", config=None, lacks="Sub-agents"),
    bash("rm in scratch after a popd is refused from the project root", "pushd sub && popd && rm __scratch__/x.txt", True, DELETE, files=(("sub/y", ""),)),
    bash("mkdir of a fresh scratch folder passes", "mkdir __scratch__/ctl-2", False),
    bash("the scratch refusal teaches no rm in scratch", "rm __scratch__/x", True, DELETE, lacks="where `rm` works"),
    bash("rm of a scratch variable in single quotes is refused", "d=__scratch__/x && rm -rf '$d'", True, DELETE),
    bash("rm of a scratch variable a loop rebinds is refused", 'd=__scratch__/x; for d in AGENTS.md; do rm -f "$d"; done', True, DELETE),
    bash("a variable of the outer shell is unknown in bash -c", 'd=__scratch__ && bash -c \' rm -rf "$d/x" \'', True, DELETE),
    bash("python -c code is not read as a shell string", 'python3 -c "rm = 1"', False, is_unchanged=True),
    bash("a scratch variable set in a subshell is unknown", '(d=__scratch__/x); rm -rf "$d"', True, DELETE),
    bash("rm inside the Claude scratchpad is refused", f"rm -rf {SCRATCHPAD}/out", True, DELETE),
        bash("rm in the scratchpad of another account is refused", f"rm -rf /tmp/claude-{os.getuid() + 1}/p/s/scratchpad/out", True, DELETE),
    bash("rm in a scratchpad outside a claude folder is refused", "rm -rf /tmp/p/scratchpad/out", True, DELETE),
    Case("an unexpected error in the guard lets the call run", ("guard.py",), {"tool_name": "Bash", "tool_input": "rm -rf /"}, False, "failed and let the call run", STRICT, is_exit_one=True),
)


def read_call(name: str, path: str, blocks: bool, text: str = "", /, **options: object) -> Case:
    event = {"tool_name": "Read", "tool_input": {"file_path": path}}

    return Case(name, ("guard.py",), event, blocks, text, **options)


SECRET = "reads or prints a credential"
SECRET_FILES = (
    "cat .env", "cat .env.local", "cat .env.production", "head -n 3 .env.staging", "cat '.env*'", "source .env", ". .env", "cat .envrc", "grep KEY .env",
    "cp .env /tmp/harness/x/env", "base64 .env", "less ~/.aws/credentials", "cat ~/.aws/sso/cache/token.json", "cat $HOME/.aws/credentials", "tail ~/.ssh/id_rsa", "cat ~/.ssh/id_ed25519",
    "cat server.pem", "cat certs/tls.key", "base64 cert.p12", "cat cert.pfx", "cat store.jks", "cat ~/.netrc", "cat ~/.git-credentials", "cat ~/.npmrc",
    "cat .npmrc", "cat ~/.pypirc", "cat terraform.tfstate", "grep password infra/prod.tfstate.backup", "cat ~/.snowflake/connections.toml",
    "cat ~/.snowflake/config.toml", "cat ~/.dbt/profiles.yml", "cat ~/.config/gh/hosts.yml", "cat ~/.docker/config.json", "cat ~/.kube/config",
    "docker run --env-file .env img", "docker run --env-file=.env img", "bash -c 'cat .env'", "cd app && cat .env", "uv run python tool.py .env",
)
SECRET_PRINTS = (
    "printenv", "printenv HOME", "printenv | grep TOKEN", "env", "env | sort", "FOO=1 env", "env -i",
    "aws secretsmanager get-secret-value --secret-id s", "aws secretsmanager batch-get-secret-value --secret-id-list s", "aws ssm get-parameter --name n --with-decryption",
    "aws ssm get-parameters --names n --with-decryption", "aws ssm get-parameters-by-path --path / --with-decryption", "aws sts get-session-token", "aws sts assume-role --role-arn r --role-session-name s",
    "aws sts assume-role-with-web-identity --role-arn r", "aws sts get-federation-token --name n", "aws configure get aws_access_key_id", "aws configure get region", "aws configure export-credentials",
    "aws ecr get-login-password", "aws ecr get-authorization-token", "aws ecr-public get-login-password", "aws eks get-token --cluster-name c", "aws rds generate-db-auth-token --hostname h",
    "aws sso get-role-credentials --role-name r", "aws s3 presign s3://b/k", "aws lambda get-function --function-name f", "aws lambda get-function-configuration --function-name f",
    "aws --profile p --region r secretsmanager get-secret-value --secret-id s", "uv run aws secretsmanager get-secret-value --secret-id s", "gh auth token", "gh --repo a/b auth token",
    "terraform output", "terraform output -json", "tofu output db_password", "terragrunt output", "terragrunt run-all output", "terraform -chdir=infra output",
)
SECRET_PASSES = (
    ".env.example", "cat .env.example", "cat .env.sample", "cat .env.template", "cat .env.dist", "cat app/.env.local.example", "cat ~/.ssh/id_ed25519.pub", "cat ~/.ssh/config", "cat ~/.ssh/known_hosts",
    "cat ~/.aws/config", "ls ~/.aws/credentials", "ls .env", "echo .env", "touch .env", "test -f .env", "cat .environment", "cat README.md", "cat src/key_store.py", "cat notes.key.md",
    "env FOO=1 make test", "env -u HOME make test", "FOO=1 env make test", "env -C /tmp ls", "aws s3 ls", "aws lambda list-functions", "aws ssm get-parameter --name n", "aws ssm get-parameters-by-path --path /",
    "aws sts get-caller-identity", "aws configure list", "aws ecr describe-repositories", "aws secretsmanager list-secrets", "aws secretsmanager describe-secret --secret-id s", "aws eks describe-cluster --name c",
    "gh auth status", "gh pr list", "terraform plan", "terraform validate", "terraform fmt", "terraform init", "terraform show", "terraform state list", "terraform state show aws_s3_bucket.b",
    "tofu plan", "terragrunt plan", "terragrunt run-all plan", "echo printenv", "grep -n env README.md", "git log --oneline",
    "find . -not -name '*.key'", "grep -e '\\.key' src", "rg -g '*.pem' x", "grep -rn --include='*.key' x .", "grep -n '.key ==' f.js", "grep -n 'a|.key' f.js", "find . -name '*.pem' -o -name '*.p12'",
)
SECRET_ASK_OFF = {"guard": {"ask_secrets": False}}
TERRAFORM_WRITES = (
    "terraform apply", "terraform apply -auto-approve", "terraform -chdir=infra apply", "terraform destroy", "terraform import aws_s3_bucket.b b", "terraform taint aws_s3_bucket.b",
    "terraform untaint aws_s3_bucket.b", "terraform force-unlock abc", "terraform state rm aws_s3_bucket.b", "terraform state mv a b", "terraform state push x.tfstate",
    "terraform state replace-provider a b", "terraform workspace delete w", "tofu apply", "tofu destroy -auto-approve", "terragrunt apply", "terragrunt run-all apply", "terragrunt run --all -- apply",
    "terragrunt destroy", "terragrunt apply-all", "terragrunt state rm a", "uvx terraform apply", "cd infra && terraform apply", "bash -c 'terraform apply'",
)
SNOW_SANDBOX_PASSES = (
    "snow sql -q 'create table t(a int)' -c sandbox", "snow sql -q 'drop table t' -c my_sandbox", "snow sql -q 'insert into t values (1)' --connection Sandbox_Dev", "snow sql -q 'create schema s' --connection=sandbox",
    "snow sql -q 'create or replace table t(a int)' -c sandbox", "snow sql -q 'drop schema_audit' -c sandbox", "snow object create table --json x -c sandbox", "snow app deploy -c sandbox",
    "snow object drop table t -c sandbox", "SNOWFLAKE_DEFAULT_CONNECTION_NAME=sandbox snow sql -q 'delete from t'", "snow sql -f write.sql -c sandbox", "cd x && snow sql -q 'truncate t' -c sandbox",
)
SNOW_SANDBOX_BLOCKS = (
    "snow sql -q 'drop database d' -c sandbox", "snow sql -q 'DROP SCHEMA IF EXISTS s' -c sandbox", "snow sql -q 'select 1; drop database d' -c sandbox", "snow sql -q 'create or replace database d' -c sandbox",
    "snow sql -q 'create or replace transient schema s' -c sandbox", "snow sql -q \"execute immediate 'drop database d'\" -c sandbox", "snow object drop database d -c sandbox", "snow object drop schema d.s -c sandbox",
    "snow sql -q 'create table t(a int)' -c sandbox_prod", "snow sql -q 'select 1' -c prod", "snow sql -q 'select 1' -c prod_sandbox", "snow sql -q 'create table t(a int)'", "snow sql -q 'create table t(a int)' -c dev",
    "snow sql -q 'create table t(a int)' -c sandbox -c dev", "snow sql -q 'create table t(a int)' -c $SANDBOX", "SNOWFLAKE_DEFAULT_CONNECTION_NAME=dev snow sql -q 'create table t(a int)'",
)
SECRET_CASES = (
    *(bash(f"secret asks: {command!r}", command, True, SECRET, config=None) for command in (*SECRET_FILES, *SECRET_PRINTS)),
    *(bash(f"secret runs: {command!r}", command, False, config=None) for command in SECRET_PASSES),
    *(agent_bash(f"secret asks a sub-agent: {command!r}", command, True, SECRET) for command in ("cat .env", "aws secretsmanager get-secret-value --secret-id s", "printenv")),
    *(read_call(f"secret read asks: {path!r}", path, True, SECRET, config=None) for path in (
        "/srv/u/app/.env", "/srv/u/app/.env.local", "/srv/u/.aws/credentials", "/srv/u/.aws/sso/cache/a.json", "/srv/u/.ssh/id_rsa", "/srv/u/.ssh/id_ed25519", "/x/server.pem", "/x/tls.key",
        "/x/a.p12", "/x/a.pfx", "/x/a.jks", "/srv/u/.netrc", "/srv/u/.git-credentials", "/srv/u/.npmrc", "/srv/u/.pypirc", "/x/terraform.tfstate", "/x/terraform.tfstate.backup",
        "/srv/u/.snowflake/connections.toml", "/srv/u/.snowflake/config.toml", "/srv/u/.dbt/profiles.yml", "/srv/u/.config/gh/hosts.yml", "/srv/u/.docker/config.json", "/srv/u/.kube/config", "/x/.envrc",
    )),
    *(read_call(f"secret read runs: {path!r}", path, False, config=None) for path in (
        "/srv/u/app/.env.example", "/srv/u/app/.env.sample", "/srv/u/app/.env.template", "/srv/u/app/.env.dist", "/srv/u/.ssh/id_ed25519.pub", "/srv/u/.ssh/config", "/srv/u/.aws/config",
        "/srv/u/app/README.md", "/srv/u/app/src/keys.py", "/srv/u/.config/other/hosts.yml",
    )),
    read_call("secret read: an override lets it run", "/srv/u/app/.env", False, config=SECRET_ASK_OFF),
    read_call("secret read: the reason is an ask", "/srv/u/app/.env", True, ASK, config=None, lacks="Blocked"),
    read_call("secret read: the reason names the file", "/srv/u/app/.env", True, "`Read /srv/u/app/.env`", config=None),
    bash("secret: the ask reason names the command", "cat .env", True, "`cat .env`", config=None, lacks="Blocked"),
    bash("secret: the ask reason says how to turn it off", "cat .env", True, "guard.ask_secrets", config=None),
    bash("secret: an override lets a secret read run", "cat .env", False, config=SECRET_ASK_OFF),
    bash("secret: an override keeps the cloud question", "aws s3 rm s3://b/k", True, CLOUD, config=SECRET_ASK_OFF),
    bash("secret: an override of the cloud question keeps the secret question", "cat .env", True, SECRET, config={"guard": {"ask_cloud": False}}),
    bash("secret: a delete beside a secret read is refused outright", "cat .env; rm a", True, "Blocked by the harness guard", config=None, lacks="permissionDecision"),
    bash("secret: a secret read through ssh asks", "ssh host cat .env", True, SECRET, config=None),
    *(bash(f"terraform asks: {command!r}", command, True, CLOUD, config=None, files=(("node_modules/.bin/terraform", ""),)) for command in TERRAFORM_WRITES),
    bash("terraform: the ask reason names the command", "terraform apply", True, "`terraform apply`", config=None, lacks="Blocked"),
    bash("terraform: an override lets apply run", "terraform apply", False, config={"guard": {"ask_cloud": False}}),
    bash("terraform: plan beside apply asks", "terraform plan && terraform apply", True, CLOUD, config=None),
    bash("terraform: help runs", "terraform apply -help", False, config=None),
    *(bash(f"snow sandbox runs: {command!r}", command, False, config=None, files=SNOW_WRITE_FILES) for command in SNOW_SANDBOX_PASSES),
    *(bash(f"snow sandbox still blocks: {command!r}", command, True, SNOW_TEXT, config=None, files=SNOW_WRITE_FILES) for command in SNOW_SANDBOX_BLOCKS),
    bash("snow sandbox: an owner-listed connection runs writes", "snow sql -q 'create table t(a int)' -c scratch_one", False, config={"guard": {"snow_sandbox_connections": ["scratch_one"]}}),
    bash("snow sandbox: a listed connection is matched whatever its case", "snow sql -q 'create table t(a int)' -c Scratch_One", False, config={"guard": {"snow_sandbox_connections": ["SCRATCH_one"]}}),
    bash("snow sandbox: a listed connection leaves the others blocked", "snow sql -q 'create table t(a int)' -c dev", True, SNOW_TEXT, config={"guard": {"snow_sandbox_connections": ["scratch_one"]}}),
    bash("snow sandbox: a listed connection holding prod stays blocked", "snow sql -q 'select 1' -c scratch_prod", True, SNOW_TEXT, config={"guard": {"snow_sandbox_connections": ["scratch_prod"]}}),
    bash("snow sandbox: a listed connection still blocks drop database", "snow sql -q 'drop database d' -c scratch_one", True, SNOW_TEXT, config={"guard": {"snow_sandbox_connections": ["scratch_one"]}}),
    bash("snow sandbox: the refusal says how to mark a sandbox", "snow sql -q 'create table t(a int)' -c dev", True, "guard.snow_sandbox_connections", config=None),
    bash("snow sandbox: a sandbox read runs", "snow sql -q 'select 1' -c sandbox", False, config=None),
)




def stop_event(report: str, /, *, agent_type: str = "harness:worker", agent_id: str = "a1") -> dict:
    return {"agent_type": agent_type, "agent_id": agent_id, "last_assistant_message": report, "session_id": SESSION}


def transcript_event(report: str, /) -> dict:

    return {**stop_event(report), "agent_transcript_path": "transcript.jsonl"}


def assistant(*blocks: dict) -> dict:
    return {"type": "assistant", "message": {"content": list(blocks)}}


def edit(tool_id: str, path: str, /) -> dict:

    return assistant({"type": "tool_use", "id": tool_id, "name": "Edit", "input": {"file_path": path}})


def answer_report(answer: str, /) -> str:

    return make_report(replace=("Answer", answer))


def exit_report(*codes: int) -> str:

    return answer_report("Changed one file. " + " ".join(f"Command {number} exit {code}." for number, code in enumerate(codes, 1)))








def gate(name: str, event: dict, blocks: bool, text: str = "", /, **options: object) -> Case:
    options.setdefault("config", {})

    return Case(name, ("report_gate.py",), event, blocks, text, **options)




def bash_call(tool_id: str, /) -> dict:
    return assistant({"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": "true"}})




CLEAN_REPORT = answer_report("Nothing changed.")
def bash_output(tool_id: str, text: str, /) -> dict:

    block = {"type": "tool_result", "tool_use_id": tool_id, "content": text}

    return {"type": "user", "message": {"content": [block]}}


def handback_event(report: str, /, *, agent_type: str = "harness:worker") -> dict:

    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "SubagentHandback",
        "tool_input": {"message": report},
        "agent_type": agent_type,
        "agent_id": "a1",
        "session_id": SESSION,
        "transcript_path": "project/s.jsonl",
    }


def handback(name: str, report: str, blocks: bool, text: str = "", /, *, lines: tuple[dict, ...] = (), **options: object) -> Case:

    options.setdefault("config", {})
    transcript = ("s/subagents/agent-a1.jsonl", "".join(f"{json.dumps(line)}\n" for line in lines))
    options["files"] = (transcript, *options.get("files", ()))
    event = handback_event(report, agent_type=str(options.pop("agent_type", "harness:worker")))
    if "event_input" in options:
        event["tool_input"] = options.pop("event_input")

    return Case(name, ("report_gate.py", "handback"), event, blocks, text, **options)


SEND_BACK_COUNT = "data/send-backs/a1.count"
EXIT_REPORT = exit_report(0)
FEEDBACK_ITEM = "skills/report/SKILL.md: add a rule to the report skill"
BAD_REPORT = make_report(skip="Not proven", replace=("Feedback", f"- {FEEDBACK_ITEM}"))
QUOTING_REPORT = answer_report("The run printed `exit 1`; the tool said it cannot find the file, so I can't say more. The tests passed. Changed src/a.py.")
LONG_REPORT = answer_report("Changed one file. " + "detail " * 3000)
OUT_OF_ORDER_REPORT = reorder_report("Not proven", "Answer", "Verdict")
GATE_CASES = (
    gate("a broken transcript line is skipped", {**transcript_event(EXIT_REPORT), "agent_transcript_path": f"{ROOT}/project/broken.jsonl"}, False, files=(("broken.jsonl", "not json\n" + json.dumps(bash_call("t1")) + "\n"),)),
    gate("a block that is no object is skipped", transcript_event(EXIT_REPORT), False, transcript=(assistant("text"), bash_call("t1"))),
    gate(
        "a message to another agent is no report",
        transcript_event("done"),
        True,
        "missing: Answer",
        transcript=(assistant({"type": "tool_use", "id": "s", "name": "SendMessage", "input": {"message": make_report()}}),),
    ),
    gate("a complete report is accepted", stop_event(make_report()), False),
    gate("a report of 20000 characters with every heading passes", stop_event(LONG_REPORT), False, lacks="characters"),
    gate("a report quoting an exit code and a cannot passes", stop_event(QUOTING_REPORT), False, lacks="could not be done"),
    gate("a report quoting an exit code and a cannot passes against an empty transcript", transcript_event(QUOTING_REPORT), False, transcript=(assistant({"type": "text", "text": "x"}),)),
    gate("a report missing a heading is sent back naming it", stop_event(make_report(skip="Verdict")), True, "- Verdict: missing: Verdict"),
    gate("a report with headings out of order is sent back naming them", stop_event(OUT_OF_ORDER_REPORT), True, "out of order: Answer"),
    handback("a handback of 20000 characters with every heading runs", LONG_REPORT, False),
    handback("a handback quoting an exit code and a cannot runs", QUOTING_REPORT, False),
    handback("a handback missing a heading is refused naming it", make_report(skip="Not proven"), True, "- Not proven: missing: Not proven"),
    handback("a handback with headings out of order is refused naming them", OUT_OF_ORDER_REPORT, True, "out of order: Answer"),
    gate("a repeated heading goes back", stop_event(make_report() + "\n## Answer\nagain"), True, "duplicated: Answer"),
    gate("a heading in a fence does not count", stop_event(make_report() + "\n```\n## Answer\n```"), False),
    gate("an unprefixed project role is not judged", stop_event(make_report(skip="Not proven"), agent_type="worker"), False),
    gate("a built-in helper is never sent back", stop_event("no headings", agent_type="Explore"), False),
    gate("another plugin's agent is never sent back", stop_event("no headings", agent_type="other:worker"), False),
    gate("web-fetch is never sent back", stop_event("The page says X.", agent_type="web-fetch"), False),
    gate("a fork is never sent back", stop_event("Done.", agent_type="fork"), False),
    gate("general-purpose is never sent back", stop_event("Done.", agent_type="general-purpose"), False),
    gate("an unknown type is never sent back", stop_event("no headings", agent_type="custom"), False),
    gate("a type that only holds the prefix is not judged", stop_event("no headings", agent_type="other-harness:worker"), False),
    gate("a harness agent not in the list is judged", stop_event("no headings", agent_type="harness:planner"), True, "missing: Answer"),
    gate(
        "an unterminated fence does not hide later headings",
        stop_event(make_report(replace=("Answer", "- output:\n```\nunterminated"))),
        False,
    ),
    gate("no project file still gates a harness role", stop_event("no headings"), True, "missing: Answer", config=None),
    gate("no project file leaves a repo's own agent alone", stop_event("no headings", agent_type="builder"), False, config=None),
    gate("a project file leaves a repo's own agent alone", stop_event("no headings", agent_type="builder"), False),
    gate(
        "a second send-back still blocks",
        stop_event(BAD_REPORT),
        True,
        "missing: Not proven",
        files=(("data/send-backs/a1.count", "1"),),
        wrote=("data/send-backs/a1.count", "2"),
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
        "missing: Not proven",
        transcript=(assistant({"type": "text", "text": CLEAN_REPORT}), assistant({"type": "text", "text": make_report(skip="Not proven")})),
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
    handback("a bad handback is refused and asks for the whole report", make_report(skip="Not proven"), True, "with the whole report"),
    handback("a good handback runs", make_report(), False),
    handback("a refused handback counts a send-back", make_report(skip="Not proven"), True, wrote=(SEND_BACK_COUNT, "1")),
    handback("a handback after three send-backs runs", make_report(skip="Not proven"), False, files=((SEND_BACK_COUNT, "3"),)),
    handback("a repo's own agent is not judged where the repo has no file", make_report(skip="Not proven"), False, config=None, agent_type="custom"),
    handback("a built-in helper's handback is never refused", make_report(skip="Not proven"), False, agent_type="Explore"),
    handback("a handback with no message is let go", "", False, event_input={}),
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
        transcript=(assistant({"type": "tool_use", "id": "h1", "name": "SubagentHandback", "input": {"message": CLEAN_REPORT}}),),
    ),
    gate(
        "a heading that is no report does not hide the handback",
        {**stop_event(""), "agent_transcript_path": "transcript.jsonl", "last_assistant_message": "## Notes\nwaiting"},
        False,
        transcript=(assistant({"type": "tool_use", "id": "h1", "name": "SubagentHandback", "input": {"message": CLEAN_REPORT}}),),
    ),
    gate(
        "a bad report by handback is not sent back, since the agent has ended",
        {**stop_event(""), "agent_transcript_path": "transcript.jsonl", "last_assistant_message": ""},
        False,
        "it has already ended",
        transcript=(assistant({"type": "tool_use", "id": "h1", "name": "SubagentHandback", "input": {"message": "## Answer\nno"}}),),
    ),
    gate(
        "a bad report by text is still sent back",
        {**stop_event("## Answer\nno"), "agent_transcript_path": "transcript.jsonl"},
        True,
        "breaks the report",
        transcript=(assistant({"type": "text", "text": "## Answer\nno"}),),
    ),
    *(gate(f"a report missing {heading} goes back", stop_event(make_report(skip=heading)), True, f"missing: {heading}") for heading in REQUIRED_HEADINGS),
    gate("a report with only the required sections is accepted", stop_event(make_report(headings=REQUIRED_HEADINGS)), False),
    *(
        gate(f"{heading} of none is accepted", stop_event(make_report(replace=(heading, "none"))), False)
        for heading in OPTIONAL_HEADINGS
    ),
    gate("an unknown heading goes back", stop_event(make_report().replace("## Open", "## Work\n- x\n## Open")), True, "not a section of the form: Work"),
    gate("an old heading goes back", stop_event(make_report() + "\n## REPORT CARD\nx"), True, "not a section of the form: REPORT CARD"),
    gate("a Verdict that is not last goes back", stop_event(make_report() + "\n## Next time\nlater"), True, "Verdict must be the last section"),
    gate("a section out of order goes back", stop_event(reorder_report("Not proven", "Answer", "Verdict")), True, "out of order: Answer"),
    gate("an optional section out of order goes back", stop_event(reorder_report("Answer", "Not proven", "Open", "Problems", "Verdict")), True, "out of order: Open"),
    *(
        gate(f"{agent} owes the one form", stop_event(make_report(headings=REQUIRED_HEADINGS), agent_type=agent), False)
        for agent in HARNESS_AGENTS
    ),
)


STRAY = "\n## Note\nstray"
BARE_REPORT = make_report(replace=("Answer", "FIRSTANSWER changed one file."), skip="Not proven")
FIX_NOT_PROVEN = "## Not proven\n- the live run was not made, the owner can run it"
VERDICT_ONLY = "## Verdict\ndone: the unit is complete"


def resend(name: str, first: str, second: str, blocks: bool, text: str = "", /, **options: object) -> Case:

    return gate(name, stop_event(second), blocks, text, before=((("report_gate.py",), stop_event(first)),), **options)


LATE_HANDBACK = "(sleep 1; printf '%s\\n' " + shlex.quote(json.dumps(assistant({"type": "tool_use", "name": "SubagentHandback", "input": {"message": FIX_NOT_PROVEN}}))) + " >> ../transcript.jsonl) >/dev/null 2>&1 &"


RESEND_CASES = (
    gate("a send-back names the wrong section", stop_event(BARE_REPORT), True, "missing: Not proven", lacks="Answer"),
    gate("a send-back asks for the sections only", stop_event(BARE_REPORT), True, "Send again only these sections", lacks="Send the WHOLE"),
    gate("a stray section is named as one to leave out", stop_event(make_report() + STRAY), True, "- Note: not a section of the form: Note (leave it out)"),
    resend("a whole new report still works", BARE_REPORT, make_report(), False),
    resend("a still wrong resend goes back again", BARE_REPORT, VERDICT_ONLY, True, "- Not proven: missing: Not proven", lacks="- Answer"),
    resend("a resend of one section does not name the others", BARE_REPORT, VERDICT_ONLY, True, lacks="Verdict:"),
    resend("a resend with a bad section next to a good one names the bad one only", BARE_REPORT, FIX_NOT_PROVEN + "\n## Bogus\nx", True, "- Bogus:", lacks="- Not proven"),
    resend("a resend in the wrong order is put right", BARE_REPORT, VERDICT_ONLY + "\n" + FIX_NOT_PROVEN, False),
    resend("a stray section is dropped by the merge", make_report() + STRAY, VERDICT_ONLY, False),
    resend("a duplicate resend is named", BARE_REPORT, FIX_NOT_PROVEN + "\n" + FIX_NOT_PROVEN, True, "duplicated: Not proven"),
    resend("an unchanged resend does not hide the old report", BARE_REPORT, BARE_REPORT, True, "missing: Not proven"),
    resend("a resend without headings keeps the old report", BARE_REPORT, "Done, fixed it.", True, "missing: Not proven"),
    gate("without a send-back a partial is judged whole", stop_event(FIX_NOT_PROVEN), True, "missing: Answer"),
    gate("a send-back counted but nothing kept is judged on the message", stop_event(FIX_NOT_PROVEN), True, "missing: Answer", files=(("data/send-backs/a1.count", "1"),)),
    gate(
        "a kept report with no send-back counted is not merged",
        stop_event(FIX_NOT_PROVEN),
        True,
        "missing: Answer",
        files=(("data/send-backs/a1.report", json.dumps({"raw": "x", "merged": make_report()})),),
    ),
    gate("an empty send-back count is zero", stop_event(FIX_NOT_PROVEN), True, "missing: Answer", files=(("data/send-backs/a1.count", ""),), lacks="let the agent stop"),
    gate("an empty kept report is ignored", stop_event(make_report()), False, files=(("data/send-backs/a1.count", "1"), ("data/send-backs/a1.report", "")), lacks="let the agent stop"),
    gate(
        "a kept report left with no send-back count is not merged",
        stop_event(make_report()),
        False,
        files=(("data/send-backs/a1.report", json.dumps({"raw": "x", "merged": "# Report: worker, STALETITLE\n" + make_report()})),),
    ),
    gate("a kept report that cannot be read is ignored", stop_event(make_report()), False, files=(("data/send-backs/a1.count", "1"), ("data/send-backs/a1.report", "not json"))),
    gate(
        "the kept report is dropped once the agent stops",
        stop_event(make_report()),
        False,
        files=(("data/send-backs/a1.count", "1"), ("data/send-backs/a1.report", json.dumps({"raw": "x", "merged": make_report()}))),
        not_wrote=("data/send-backs/a1.report", "merged"),
    ),
)




class Launch(NamedTuple):

    call: dict
    result: dict


def launch(tool_id: str, /, *, is_background: bool = True, is_marked: bool = True) -> Launch:

    tool_input: dict[str, object] = {"description": "audit"}
    if is_marked:
        tool_input["run_in_background"] = is_background
    use = {"type": "tool_use", "id": tool_id, "name": "Agent", "input": tool_input}
    reply = "Async agent launched successfully." if is_background else "The agent finished."
    result = {"type": "tool_result", "tool_use_id": tool_id, "content": [{"type": "text", "text": reply}]}

    return Launch(
        {"type": "assistant", "message": {"role": "assistant", "content": [use]}},
        {"type": "user", "message": {"role": "user", "content": [result]}},
    )


def notify(tool_id: str, status: str, /) -> dict:
    body = f"<task-notification>\n<tool-use-id>{tool_id}</tool-use-id>\n<status>{status}</status>\n</task-notification>"

    return {"type": "user", "message": {"role": "user", "content": body}}


def queued_notify(tool_id: str, /) -> dict:

    body = notify(tool_id, "completed")["message"]["content"]

    return {"type": "attachment", "attachment": {"type": "queued_command", "prompt": body}}


def queue_notify(tool_id: str, /) -> dict:

    return {"type": "queue-operation", "operation": "enqueue", "content": notify(tool_id, "completed")["message"]["content"]}


def both_notify() -> dict:

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
    extra: dict | None = None,
    **options: object,
) -> Case:
    event = {"session_id": SESSION, "last_assistant_message": message, "transcript_path": "transcript.jsonl", **(extra or {})}
    counted = (f"data/turns/{SESSION}.calls", "".join(f"{call}\n" for call in calls or []))
    options.setdefault("config", {})

    return Case(name, ("turn.py", "stop"), event, blocks, text, files=(counted, *files), transcript=transcript, **options)


BLOCKS_FILE = f"data/turns/{SESSION}.blocks"
CALLS_FILE = f"data/turns/{SESSION}.calls"
DEFERRED_FILE = f"data/turns/{SESSION}.deferred"
TURN_CASES = (
    turn("the status is read from the transcript when the event has none", "", False, calls=BUSY_CALLS, transcript=(assistant({"type": "text", "text": FULL_STATUS}),)),
    turn("a transcript line that is no object is skipped", "", False, transcript=(12, assistant({"type": "text", "text": "Done."}))),
    turn("a last line that is a tool call does not crash", "", False, transcript=(assistant({"type": "text", "text": "Done."}), assistant({"type": "tool_use", "id": "t", "name": "Bash", "input": {}}))),
    Case("no mode does nothing", ("turn.py",), {"session_id": SESSION}, False, config={}),
    turn("an agent's finish in a queued command is seen", "Done.", True, "needs the job status", calls=BUSY_CALLS, transcript=(*launch("t1"), queued_notify("t1"))),
    turn("an agent's finish in a queue operation is seen", "Done.", True, "needs the job status", calls=BUSY_CALLS, transcript=(*launch("t1"), queue_notify("t1"))),
    turn("a turn that ran a named agent gets a note to list it under Agents", FULL_STATUS, False, "Missing: Audit the parser", calls=["Agent\tAudit the parser", "Edit", "Edit"]),
    turn("a soft check alone gives a note and no hold", FULL_STATUS, False, "Note, the turn is not held", calls=["Agent\tAudit the parser", "Edit", "Edit"], lacks="decision", wrote=(BLOCKS_FILE, "0")),
    turn("a soft check alone ends the turn as passed", FULL_STATUS, False, calls=["Agent\tAudit the parser", "Edit", "Edit"], files=((BLOCKS_FILE, "2"),), not_wrote=(CALLS_FILE, "Agent"), wrote=(BLOCKS_FILE, "0")),
    turn("a soft check beside a hard one holds the turn for the hard one", "Done.", True, "note, does not hold the turn", calls=["Agent\tAudit the parser", "Edit", "Edit"]),
    turn("an Agents section naming each agent passes", f"{FULL_STATUS}\n## Agents\n- audit the parser: done, problems none", False, calls=["Agent\tAudit the parser", "Edit", "Edit"]),
    turn("an agent named outside the Agents section gets a note", f"{FULL_STATUS}\n## Agents\n- other\n## Notes\naudit the parser", False, "Missing", calls=["Agent\tAudit the parser", "Edit", "Edit"]),
    Case("add keeps an agent's description", ("turn.py", "add"), {"session_id": SESSION, "tool_name": "Agent", "tool_input": {"description": "audit  the\nparser"}}, False, config={}, wrote=(CALLS_FILE, "Agent\taudit the parser")),
    Case("add keeps another tool's name alone", ("turn.py", "add"), {"session_id": SESSION, "tool_name": "Edit", "tool_input": {"description": "x"}}, False, config={}, wrote=(CALLS_FILE, "Edit"), not_wrote=(CALLS_FILE, "\t")),
    turn(
        "a Bash result that quotes the launch text is no running agent",
        "Done.",
        True,
        "needs the job status",
        calls=BUSY_CALLS,
        transcript=(
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "rg launched t.jsonl"}}]}},
            bash_output("b1", "Async agent launched successfully."),
        ),
    ),
    turn(
        "check_agents reads agent lines only, not an edit's path",
        f"{FULL_STATUS}\n## Agents\n- audit: done",
        False,
        calls=("Agent\taudit", "Edit\tsrc/a.py", "Edit\tsrc/b.py", "Edit\tsrc/c.py"),
    ),
    Case("add keeps an edit's path", ("turn.py", "add"), {"session_id": SESSION, "tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}}, False, config={}, wrote=(CALLS_FILE, "Edit\tsrc/a.py")),
    Case("add keeps a notebook edit's path", ("turn.py", "add"), {"session_id": SESSION, "tool_name": "NotebookEdit", "tool_input": {"notebook_path": "n.ipynb"}}, False, config={}, wrote=(CALLS_FILE, "NotebookEdit\tn.ipynb")),
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
    turn("the full status with no agent is allowed", FULL_STATUS, False, calls=BUSY_CALLS),
    turn("two calls need no status", PROGRESS, False, calls=["Edit", "Edit"]),
    turn("the Stop hook ignores a heading in a fence", f"```\n{FULL_STATUS}\n```", True, "Verdict", calls=BUSY_CALLS),
    turn("a project's min_calls is read", PROGRESS, False, calls=BUSY_CALLS, config={"stop": {"min_calls": 5}}),
    turn("no project file still asks for the closing status", PROGRESS, True, "job status", calls=BUSY_CALLS, config=None),
    turn("an empty blocks file counts as zero", PROGRESS, True, "Verdict", calls=BUSY_CALLS, files=((BLOCKS_FILE, ""),), lacks="let the call run", wrote=(BLOCKS_FILE, "1")),
    turn(
        "the third block is the last",
        PROGRESS,
        True,
        "Verdict",
        calls=BUSY_CALLS,
        files=((BLOCKS_FILE, "2"),),
        wrote=(BLOCKS_FILE, "3"),
    ),
    turn(
        "past the last block the turn ends with a warning",
        PROGRESS,
        False,
        "open checks",
        calls=BUSY_CALLS,
        files=((BLOCKS_FILE, "3"),),
    ),
    turn("a project's headings replace the status", "## Result\nall of it", False, calls=BUSY_CALLS, config={"stop": {"headings": ["Result"]}}),
    turn("a project's missing heading is named", PROGRESS, True, "Result", calls=BUSY_CALLS, config={"stop": {"headings": ["Result"]}}),
    turn("a stopped agent is finished", PROGRESS, True, "Verdict", calls=BUSY_CALLS, transcript=(*launch("t1"), notify("t1", "stopped"))),
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
    turn("a progress note keeps the count", PROGRESS, False, calls=BUSY_CALLS, transcript=launch("t1"), wrote=(CALLS_FILE, "Agent"), config={}),
    turn("a progress note marks the status as due", PROGRESS, False, calls=BUSY_CALLS, transcript=launch("t1"), wrote=(DEFERRED_FILE, "1")),
    turn("the status empties the count", FULL_STATUS, False, calls=BUSY_CALLS, not_wrote=(CALLS_FILE, "Agent")),
    turn(
        "the status clears the due mark",
        FULL_STATUS,
        False,
        calls=BUSY_CALLS,
        files=((DEFERRED_FILE, "1"),),
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
    turn("a fence that never closes does not hide the status", FULL_STATUS + "\n```\nopen", False, calls=BUSY_CALLS),
    turn("the project variable counts past a cd", PROGRESS, True, "Verdict", calls=BUSY_CALLS, cwd="elsewhere", project_dir="project"),
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
        "reset keeps the count when a status is due",
        ("turn.py", "reset"),
        {"session_id": SESSION, "prompt": "<task-notification>"},
        False,
        config={},
        files=((CALLS_FILE, "Agent\nEdit\n"), (DEFERRED_FILE, "1")),
        wrote=(CALLS_FILE, "Agent\nEdit\n"),
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
        "add counts with no project file",
        ("turn.py", "add"),
        {"session_id": SESSION, "tool_name": "Edit"},
        False,
        wrote=(f"data/turns/{SESSION}.calls", "Edit"),
    ),
)

OLD, NEW = "2020-01-01T00:00:00.000Z", "2999-01-01T00:00:00.000Z"


def budget(name: str, brief_text: str, blocks: bool, text: str = "", /, *, turns: int = 100, role: str = "harness:worker", **options: object) -> Case:

    first = {"type": "user", "timestamp": OLD, "message": {"role": "user", "content": brief_text}}
    lines = [json.dumps({"type": "assistant", "timestamp": NEW, "message": {"id": f"m{index}", "content": [{"type": "tool_use", "id": f"t{index}", "name": "Bash", "input": {}}]}}) for index in range(turns)]
    options.setdefault("config", {})
    transcript = ("s/subagents/agent-a1.jsonl", json.dumps(first) + "\n" + "\n".join(lines) + "\n")
    files = options.get("files")
    options["files"] = (transcript,) if files is None else (transcript, *files) if files else ()
    event = {"tool_name": "Bash", "agent_id": "a1", "agent_type": role, "transcript_path": "project/s.jsonl", "tool_use_id": f"t{turns - 1}"}

    return Case(name, ("budget.py",), {**event, **options.pop("event", {})}, blocks, text, **options)


def turn_line(index: int, message_id: str = "", /) -> str:

    return json.dumps({"type": "assistant", "timestamp": NEW, "message": {"id": message_id or f"m{index}", "content": [{"type": "tool_use", "id": f"t{index}", "name": "Bash", "input": {}}]}}) + "\n"


BUDGET_HEAD = json.dumps({"type": "user", "timestamp": OLD, "message": {"role": "user", "content": "Goal: x"}}) + "\n"
BUDGET_STATE = "data/budget/a1.turns"


def saved_count(name: str, lines: str, saved: dict, blocks: bool, text: str = "", /, **options: object) -> Case:

    event = {"tool_use_id": None, **options.pop("event", {})}
    state = (BUDGET_STATE, json.dumps(saved))

    return budget(name, "Goal: x", blocks, text, files=(("s/subagents/agent-a1.jsonl", BUDGET_HEAD + lines), state), event=event, **options)


BUDGET_CASES = (
    saved_count("a saved count from past the end of the file starts over", turn_line(1) + turn_line(2), {"offset": 10**9, "count": 80, "last_id": None}, False),
    saved_count("a saved count that cannot be read starts over", turn_line(1), {"offset": "x", "count": 80, "last_id": None}, False),
    saved_count("a message split across calls is one turn", turn_line(5, "m5"), {"offset": len(BUDGET_HEAD), "count": 70, "last_id": "m5"}, False),
    saved_count("a line with three calls is one turn", json.dumps({"type": "assistant", "message": {"id": "m1", "content": [{"type": "tool_use", "id": call, "name": "Read"} for call in ("a", "b", "c")]}}) + "\n", {"offset": len(BUDGET_HEAD), "count": 69, "last_id": None}, False),
    budget("an agent whose file cannot be found passes", "Goal: x", False, files=(), event={"transcript_path": "", "tool_use_id": None}),
    budget("a spent budget lets TaskStop through", "Budget: 30", False, turns=31, event={"tool_name": "TaskStop"}),
    budget("a spent budget lets KillShell through", "Budget: 30", False, turns=31, event={"tool_name": "KillShell"}),
    budget("no note one turn before", "Budget: 30", False, lacks="additionalContext", turns=23),
    budget("no note one turn after", "Budget: 30", False, lacks="additionalContext", turns=25),
    budget("a worker at its default budget passes", "Goal: x", False, turns=70),
    budget("calls of one message are one turn", "Budget: 1", False, files=(("s/subagents/agent-a1.jsonl", json.dumps({"timestamp": OLD, "message": {"content": "Budget: 1"}}) + "\n" + "".join(json.dumps({"type": "assistant", "message": {"id": "m1", "content": [{"type": "tool_use", "id": call, "name": "Read"}]}}) + "\n" for call in ("a", "b", "c"))),), event={"tool_use_id": "c"}),
    budget("an event with no call id counts what is written", "Goal: x", False, turns=70, event={"tool_use_id": None}),
    budget("the brief's Budget line replaces the default", "Goal: x\nBudget: 99999999", False),
    budget("Budget: N turns counts", "Goal: x\nBudget: 99999999 turns", False),
    budget("the budget ends its own sentence", "Goal: x\nBudget: 99999999 turns. Throwaway folder: `__scratch__/a/`.", False),
    budget("the budget sits inside a line", "Runs: smallest first. Budget: 99999999 turns. Folder: a", False),
    budget("a handback past the budget passes", "Goal: x", False, event={"tool_name": "SubagentHandback"}),
    budget("a scout at 35 turns passes", "Goal: x", False, role="scout", turns=35),
    budget("the project's budget replaces the defaults", "Goal: x", False, config={"budget": {"worker": 99999999}}),
    budget("a role with no budget entry passes", "Goal: x", False, config={"budget": {"scout": 1}}),
    budget("another agent type inside the default passes", "Goal: x", False, role="Explore", turns=40),
    budget("the main session passes", "Goal: x", False, event={"agent_id": None, "agent_transcript_path": "project/s/subagents/agent-a1.jsonl"}),
    budget("a missing transcript passes the budget", "Goal: x", False, files=()),
    budget("an empty transcript has the role's default", "Goal: x", False, files=(("s/subagents/agent-a1.jsonl", ""),)),
    budget("a broken transcript has the role's default", "Goal: x", False, files=(("s/subagents/agent-a1.jsonl", "{not json\n"),)),
)






class File(NamedTuple):

    name: str
    text: str


def replay_transcript(name: str, commands: tuple[tuple[str, str], ...], /) -> File:

    lines = (
        {"type": "assistant", "cwd": folder, "message": {"content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": command}}]}}
        for command, folder in commands
    )

    return File(f"../.claude/projects/p/{name}.jsonl", "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines))


REPLAY_WORK = ("../work/x.txt", "x\n")
TOOL_CASES = (
    Case("the replay counts a refused command", ("replay.py",), {}, False, "refused: 1 distinct", files=(("../.claude/projects/p/s.jsonl", json.dumps({"type": "assistant", "cwd": "/", "message": {"content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "rm x"}}]}}, separators=(",", ":")) + "\n"),)),
    Case("the replay does not refuse a soft rule", ("replay.py",), {}, False, "refused: 0 distinct", files=(replay_transcript("s", (("pytest -q | tail -3", "/"),)),)),
    Case("the replay lists a soft rule apart", ("replay.py",), {}, False, "run with a note: 1 distinct", files=(replay_transcript("s", (("pytest -q | tail -3", "/"),)),)),
    Case("a command in two sessions is listed once", ("replay.py",), {}, False, "== refused delete: 1", files=(replay_transcript("s", (("rm x", "/"),)), replay_transcript("t", (("rm x", "/"),)))),
    Case("a glob is matched in the folder of its transcript line", ("replay.py",), {}, False, "refused: 0 distinct", files=(replay_transcript("s", (("ls x.*", "@ROOT@/work"),)), REPLAY_WORK)),
    Case("a glob with no match there is refused", ("replay.py",), {}, False, "== refused glob: 1", files=(replay_transcript("s", (("ls y.*", "@ROOT@/work"),)), REPLAY_WORK)),
)




def context(name: str, event: dict, text: str = "", /, **options: object) -> Case:
    options.setdefault("config", {})

    return Case(name, ("context.py",), event, False, text, **options)


FORM_FRAGMENT = "Answer, Not proven, then only if they have something to say Problems, Next time, Open and Feedback, then Verdict"
CONTEXT_CASES = (
    context("a worker start carries the editing habits", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "## Edit and check in one call"),
    context("a scout start leaves out the editing habits", {"hook_event_name": "SubagentStart", "agent_type": "harness:scout"}, "## Read", lacks="## Edit and check in one call"),
    context("a reviewer start leaves out the clean and git habits", {"hook_event_name": "SubagentStart", "agent_type": "harness:reviewer"}, "## When a call is refused", lacks="## Clean"),
    context("a helper start keeps the editing habits and leaves out the git one", {"hook_event_name": "SubagentStart", "agent_type": "Explore"}, "## Clean", lacks="## Git"),
    context("a worker start leaves out the git habit", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "## Clean", lacks="## Git"),
    context("a session start keeps the git habit", {"hook_event_name": "SessionStart"}, "## Git"),
    context("a sub-agent's session start is not told to load the orchestrator", {"hook_event_name": "SessionStart", "agent_id": "a1", "agent_type": "harness:worker"}, "few tool turns", lacks="harness:orchestrator"),
    context("a sub-agent is told to run long checks in the background", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "run a long check in the background"),
    context("a sub-agent is told what stands in for Grep", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "use `rg` and `find`"),
    context("a session is told what stands in for Grep", {"hook_event_name": "SessionStart"}, "use `rg` and `find`"),
    context("a zsh user's agent is told the shell", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "The shell is zsh"),
    context("another shell is not called zsh", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, lacks="The shell is zsh", shell="/bin/bash"),
    context("the scratch folder is named", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "Throwaway files go in `/tmp/harness/project/`"),
    context("the old temporary folder note is gone", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, lacks="runs, with a note"),
    context("a session start makes the state folder with a map", {"hook_event_name": "SessionStart"}, wrote=("state/harness/project/README.md", "kept outside the project")),
    context("a session start makes no folder in the project", {"hook_event_name": "SessionStart"}, not_wrote=("__harness__/README.md", "harness")),
    context("a session start copies an old harness folder when the new one is empty", {"hook_event_name": "SessionStart"}, wrote=("state/harness/project/notes.md", "old"), files=(("__harness__/notes.md", "old"),)),
    context("a session start leaves the old harness folder in place", {"hook_event_name": "SessionStart"}, wrote=("__harness__/notes.md", "old"), files=(("__harness__/notes.md", "old"),)),
    context("a session start does not copy into a state folder that holds files", {"hook_event_name": "SessionStart"}, not_wrote=("state/harness/project/notes.md", "old"), files=(("state/harness/project/keep.md", "x"), ("__harness__/notes.md", "old"))),
    context("a session start names the orchestrator", {"hook_event_name": "SessionStart"}, "harness:orchestrator"),
    context("a session start's output is hook-specific", {"hook_event_name": "SessionStart"}, '"hookEventName": "SessionStart"'),
    *(
        context(f"{agent} is left to its preloaded report skill", {"hook_event_name": "SubagentStart", "agent_type": agent}, lacks=FORM_FRAGMENT)
        if agent.startswith("harness:")
        else context(f"{agent} is told the report form", {"hook_event_name": "SubagentStart", "agent_type": agent}, FORM_FRAGMENT)
        for agent in AGENT_TYPES
    ),
    context("a session start is not told the report form", {"hook_event_name": "SessionStart"}, lacks="Not proven"),
    context("a helper is not told that a hook checks its report", {"hook_event_name": "SubagentStart", "agent_type": "Explore"}, lacks="A hook sends back"),
    context("a session start states the tool-turn rule", {"hook_event_name": "SessionStart"}, "few tool turns"),
    context("a session start carries the tool-habits skill", {"hook_event_name": "SessionStart"}, "## When a call is refused"),
    context("a sub-agent start carries the tool-habits skill", {"hook_event_name": "SubagentStart", "agent_type": "Explore"}, "## When a call is refused"),
    context("the skill's front matter is not injected", {"hook_event_name": "SessionStart"}, lacks="description: How to make tool calls"),
    context("a worker is told the tool-turn rule", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, "few tool turns"),
    context("a missing skill falls back to a pointer", {"hook_event_name": "SessionStart"}, "Load the `harness:tool-habits` skill", plugin_root="nowhere"),
    context("a helper is told the tool-turn rule", {"hook_event_name": "SubagentStart", "agent_type": "Explore"}, "few tool turns"),
    context("no project file still gets the context", {"hook_event_name": "SessionStart"}, "orchestrator", config=None),
    context("a broken owner file still starts the session with its context", {"hook_event_name": "SessionStart"}, "orchestrator", config=None, files=(("data/user.json", "{not json"),)),
    context("the project variable finds the project", {"hook_event_name": "SessionStart"}, "orchestrator", cwd="elsewhere", project_dir="project"),
)


PROGRESS_FILE = "data/progress/case-session.jsonl"
PROGRESS_OFFSET = "data/progress/case-session.offset"


def progress_line(agent: str, calls: int, limit: int | None, tool: str, summary: str, /, *, role: str = "harness:worker") -> str:

    return json.dumps({"time": "2026-01-01T00:00:00+00:00", "agent_id": agent, "agent_type": role, "calls": calls, "budget": limit, "tool": tool, "summary": summary}) + "\n"


def agent_progress(name: str, turns: int, /, *, wrote: str = "", not_wrote: str = "", tool_input: dict | None = None, **options: object) -> Case:

    event = {"session_id": SESSION, "tool_input": tool_input or {}, **options.pop("event", {})}

    return budget(name, "Goal: x", False, turns=turns, event=event, wrote=(PROGRESS_FILE, wrote) if wrote else None, not_wrote=(PROGRESS_FILE, not_wrote) if not_wrote else None, **options)


def main_progress(name: str, text: str | None, /, *, offset: int | None = None, wrote: str = "", **options: object) -> Case:

    files = ((PROGRESS_FILE, text),) if text is not None else ()
    files += ((PROGRESS_OFFSET, str(offset)),) if offset is not None else ()

    return Case(name, ("budget.py",), {"session_id": SESSION, "tool_name": "Bash", "tool_input": {}}, False, config={}, files=files, wrote=(PROGRESS_OFFSET, wrote) if wrote else None, **options)


AGED_PROGRESS = (("data/progress/old.jsonl", "gone"), ("data/progress/old.offset", "1"), ("data/progress/recent.jsonl", "kept"))
AGE_PROGRESS = ("touch -d '8 days ago' ../data/progress/old.jsonl ../data/progress/old.offset", "touch -d '6 days ago' ../data/progress/recent.jsonl")
AGED_EVENT = {"session_id": SESSION, "tool_input": {}}

FIRST = progress_line("abcdef123456", 30, 70, "Bash", "make check")
SECOND = progress_line("fedcba654321", 10, 35, "Read", "src/a.py", role="harness:scout")
PARALLEL_TURNS = "".join(json.dumps({"type": "assistant", "timestamp": NEW, "message": {"id": f"m{index}", "content": [{"type": "tool_use", "id": f"t{index}", "name": "Bash", "input": {}}]}}) + "\n" for index in range(9))
PARALLEL_LAST = "".join(json.dumps({"type": "assistant", "timestamp": NEW, "message": {"id": "m9", "content": [{"type": "tool_use", "id": call, "name": "Bash", "input": {}}]}}) + "\n" for call in ("t9a", "t9b"))
PARALLEL_FILES = (("s/subagents/agent-a1.jsonl", json.dumps({"type": "user", "timestamp": OLD, "message": {"role": "user", "content": "Goal: x"}}) + "\n" + PARALLEL_TURNS + PARALLEL_LAST),)
PROGRESS_CASES = (
    agent_progress("progress: a line is written at the 10th turn", 10, wrote='"calls": 10'),
    agent_progress("progress: no line at the 9th turn", 9, not_wrote='"calls"'),
    agent_progress("progress: the interval comes from the config", 5, wrote='"calls": 5', config={"progress": {"every": 5}}),
    agent_progress("progress: every 0 turns it off", 10, not_wrote='"calls"', config={"progress": {"every": 0}}),
    budget("progress: a new line deletes the files of a week ago", "Goal: x", False, turns=10, event=AGED_EVENT, files=AGED_PROGRESS, git=AGE_PROGRESS, not_wrote=("data/progress/old.jsonl", "gone"), wrote=("data/progress/recent.jsonl", "kept")),
    budget("progress: an old offset goes with its file", "Goal: x", False, turns=10, event=AGED_EVENT, files=AGED_PROGRESS, git=AGE_PROGRESS, not_wrote=("data/progress/old.offset", "1")),
    budget("progress: no new line deletes nothing", "Goal: x", False, turns=9, event=AGED_EVENT, files=AGED_PROGRESS, git=AGE_PROGRESS, wrote=("data/progress/old.jsonl", "gone")),
    agent_progress("progress: the line names the tool and the call", 10, wrote='"tool": "Bash", "summary": "make check"', tool_input={"command": "make check"}),
    agent_progress("progress: a file path is the summary of an edit", 10, wrote='"summary": "src/a.py"', tool_input={"file_path": "src/a.py", "old_string": "x"}),
    agent_progress("progress: the summary is cut to 80 characters", 10, wrote="x" * 80 + '"', not_wrote="x" * 81, tool_input={"command": "x" * 200}),
    agent_progress("progress: the line holds a time", 10, wrote='"time": "20'),
    agent_progress("progress: the line holds the agent and its role", 10, wrote='"agent_id": "a1", "agent_type": "harness:worker"'),
    agent_progress("progress: the first call of a turn writes", 10, wrote='"calls": 10', files=PARALLEL_FILES, event={"tool_use_id": "t9a"}),
    agent_progress("progress: a later call of the same turn writes nothing", 10, not_wrote='"calls"', files=PARALLEL_FILES, event={"tool_use_id": "t9b"}),
    Case("progress: an agent call reads no notes", ("budget.py",), budget("x", "Goal: x", False, turns=3, event={"session_id": SESSION}).event, False, lacks="Agent progress", config={}, files=budget("x", "Goal: x", False, turns=3).files + ((PROGRESS_FILE, FIRST),)),
    main_progress("progress: the main session gets the latest lines as one note", FIRST, context="Agent progress: worker abcdef at 30 turns, last: Bash make check"),
    main_progress("progress: two agents share one note", FIRST + SECOND, context="; scout fedcba at 10 turns, last: Read src/a.py"),
    main_progress("progress: an agent shows its latest line only", progress_line("abcdef123456", 10, 70, "Bash", "old") + FIRST, context="at 30 turns", context_lacks="at 10 turns"),
    main_progress("progress: lines before the saved offset are not told again", FIRST + SECOND, offset=len(FIRST), context="scout fedcba", context_lacks="worker abcdef"),
    main_progress("progress: the offset moves past the lines read", FIRST + SECOND, wrote=str(len(FIRST + SECOND)), context="Agent progress"),
    main_progress("progress: nothing new is silent", FIRST, offset=len(FIRST), lacks="Agent progress", is_unchanged=True),
    main_progress("progress: an unfinished line waits for its newline", FIRST + SECOND[:-1], wrote=str(len(FIRST)), context="worker abcdef", context_lacks="scout"),
    main_progress("progress: an offset past the end starts over", FIRST, offset=99999, context="worker abcdef"),
    main_progress("progress: a torn line is skipped", "{not json\n" + SECOND, context="scout fedcba"),
    main_progress("progress: no file is silent", None, lacks="Agent progress"),
)


def commit(name: str, command: str, blocks: bool, text: str = "", /, **options: object) -> Case:
    options.setdefault("config", {})

    return Case(name, ("commit_gate.py",), {"tool_name": "Bash", "tool_input": {"command": command}}, blocks, text, **options)


GOOD_MESSAGE = "feat(x): add y\n\n* did it\n* because z"
TWO_TESTS = "def test_a():\n    assert 1\n\ndef test_b():\n    assert 1\n"
ONE_TEST = "def test_a():\n    assert 1\n"
ASYNC_TESTS = "async def test_a():\n    assert 1\n\nasync def test_b():\n    assert 1\n"
TWO_SPECS = "it('a', () => {});\ntest('b', () => {});\n"
BASE = "git init -q && git add -A && git commit -qm base"
STAGE_ONE = "printf 'def test_a():\\n    assert 1\\n' > tests/test_x.py && git add -A"
WITH_REASON = GOOD_MESSAGE + "\n* Tests removed: the feature is gone"
DROP = "this commit drops tests"
KEPT_FILES = (("tests/test_x.py", TWO_TESTS),)
AT = "@"


def kept(name: str, command: str, blocks: bool, text: str = "", /, *, setup: tuple[str, ...] = (BASE, STAGE_ONE), files: tuple[tuple[str, str], ...] = KEPT_FILES, **options: object) -> Case:

    return commit(name, command, blocks, text, files=files, git=setup, **options)


KEPT_CASES = (
    kept("a commit that drops a test is refused", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/test_x.py 2 -> 1"),
    kept("the refusal says how to explain the drop", f"git commit -m '{GOOD_MESSAGE}'", True, "* Tests removed: <why>"),
    kept("a deleted test file counts all its tests", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/test_x.py (deleted) 2 -> 0", setup=(BASE, "git rm -q tests/test_x.py")),
    kept("a Tests removed bullet with a reason passes", f"git commit -m '{WITH_REASON}'", False),
    kept("a Tests removed bullet with no reason is refused", f"git commit -m '{GOOD_MESSAGE}\n* Tests removed:'", True, DROP),
    kept("a renamed test file with the same count passes", f"git commit -m '{GOOD_MESSAGE}'", False, setup=(BASE, "git mv tests/test_x.py tests/test_y.py")),
    kept("a rename out of the test folders loses its tests", f"git commit -m '{GOOD_MESSAGE}'", True, "2 -> 0", setup=(BASE, "mkdir src && git mv tests/test_x.py src/x.py")),
    kept("an unstaged drop passes without -a", f"git commit -m '{GOOD_MESSAGE}'", False, setup=(BASE, "printf 'def test_a():\\n    assert 1\\n' > tests/test_x.py")),
    kept("an unstaged drop is refused with -a", f"git commit -a -m '{GOOD_MESSAGE}'", True, DROP, setup=(BASE, "printf 'def test_a():\\n    assert 1\\n' > tests/test_x.py")),
    kept("an unstaged drop is refused with a -am cluster", f"git commit -am '{GOOD_MESSAGE}'", True, DROP, setup=(BASE, "printf 'def test_a():\\n    assert 1\\n' > tests/test_x.py")),
    kept("an unstaged drop is refused with --all", f"git commit --all -m '{GOOD_MESSAGE}'", True, DROP, setup=(BASE, "printf 'def test_a():\\n    assert 1\\n' > tests/test_x.py")),
    kept("a drop staged by an add in the same command is refused", f"git add -A && git commit -m '{GOOD_MESSAGE}'", True, DROP, setup=(BASE, "printf 'def test_a():\\n    assert 1\\n' > tests/test_x.py")),
    kept("a first commit passes", f"git commit -m '{GOOD_MESSAGE}'", False, setup=("git init -q", STAGE_ONE)),
    kept("a folder that is no repository passes", f"git commit -m '{GOOD_MESSAGE}'", False, setup=()),
    kept("the rule can be turned off", f"git commit -m '{GOOD_MESSAGE}'", False, config={"tests_kept": {"enabled": False}}),
    kept("added tests pass", f"git commit -m '{GOOD_MESSAGE}'", False, files=(("tests/test_x.py", ONE_TEST),), setup=(BASE, "printf 'def test_a():\\n    assert 1\\n\\ndef test_b():\\n    assert 1\\n' > tests/test_x.py && git add -A")),
    kept("a drop in a source file passes", f"git commit -m '{GOOD_MESSAGE}'", False, files=(("src/app.py", TWO_TESTS),), setup=(BASE, "printf 'x = 1\\n' > src/app.py && git add -A")),
    kept("async tests in a file that does not parse are counted", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/test_x.py 2 -> 1", files=(("tests/test_x.py", ASYNC_TESTS + "x = (\n"),), setup=(BASE, "printf 'async def test_a():\\n    assert 1\\nx = (\\n' > tests/test_x.py && git add -A")),
    kept("async tests are counted in source that does not parse", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/test_x.py 2 -> 1", files=(("tests/test_x.py", ASYNC_TESTS + "x = (\n"),), setup=(BASE, "printf 'async def test_a():\\n    assert 1\\nx = (\\n' > tests/test_x.py && git add -A")),
    kept("async tests are counted", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/test_x.py 2 -> 1", files=(("tests/test_x.py", ASYNC_TESTS),), setup=(BASE, "printf 'async def test_a():\\n    assert 1\\n' > tests/test_x.py && git add -A")),
    kept("script tests are counted", f"git commit -m '{GOOD_MESSAGE}'", True, "web/a.test.js 2 -> 1", files=(("web/a.test.js", TWO_SPECS),), setup=(BASE, "printf \"it('a', () => {});\\n\" > web/a.test.js && git add -A")),
    kept("any file under a tests folder is a test file", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/helpers/util.py 2 -> 1", files=(("tests/helpers/util.py", TWO_TESTS),), setup=(BASE, "printf 'def test_a():\\n    assert 1\\n' > tests/helpers/util.py && git add -A")),
    kept("a drop in one file offset by a gain in another passes", f"git commit -m '{GOOD_MESSAGE}'", False, setup=(BASE, STAGE_ONE.replace("&&", "&& cp tests/test_x.py tests/test_z.py &&"))),
    kept("a drop is refused beside a style problem too", "git commit -m 'add y'", True, DROP),
    kept("named paths are read from the working tree", f"git commit tests/test_x.py -m '{GOOD_MESSAGE}'", True, DROP, setup=(BASE, "printf 'def test_a():\\n    assert 1\\n' > tests/test_x.py")),
    kept("named paths with -o are read from the working tree", f"git commit -o tests/test_x.py -m '{GOOD_MESSAGE}'", True, DROP, setup=(BASE, "printf 'def test_a():\\n    assert 1\\n' > tests/test_x.py")),
    kept("named paths without the test file pass", f"git commit src/app.py -m '{GOOD_MESSAGE}'", False, files=(*KEPT_FILES, ("src/app.py", "x = 1\n")), setup=(BASE, "printf 'def test_a():\\n    assert 1\\n' > tests/test_x.py && printf 'x = 2\\n' > src/app.py")),
    kept("a test of only pass counts for nothing", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/test_x.py 2 -> 1", setup=(BASE, "printf 'def test_a():\\n    assert 1\\n\\ndef test_b():\\n    pass\\n' > tests/test_x.py && git add -A")),
    kept("a test of only a docstring and ... counts for nothing", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/test_x.py 2 -> 1", files=(*KEPT_FILES, ("new.txt", 'def test_a():\n    assert 1\n\ndef test_b():\n    """x"""\n    ...\n')), setup=(BASE, "cp new.txt tests/test_x.py && git add -A")),
    kept("a pytest-skipped test counts for nothing", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/test_x.py 2 -> 1", files=(*KEPT_FILES, ("new.txt", "def test_a():\n    assert 1\n\n" + AT + "pytest.mark.skip(reason='x')\ndef test_b():\n    assert 1\n")), setup=(BASE, "cp new.txt tests/test_x.py && git add -A")),
    kept("a unittest-skipped test counts for nothing", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/test_x.py 2 -> 1", files=(*KEPT_FILES, ("new.txt", "def test_a():\n    assert 1\n\n" + AT + "unittest.skip('x')\ndef test_b():\n    assert 1\n")), setup=(BASE, "cp new.txt tests/test_x.py && git add -A")),
    kept("a bare skip decorator counts for nothing", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/test_x.py 2 -> 1", files=(*KEPT_FILES, ("new.txt", 'def test_a():\n    assert 1\n\n@skip\ndef test_b():\n    assert 1\n')), setup=(BASE, "cp new.txt tests/test_x.py && git add -A")),
    kept("an it.skip test counts for nothing", f"git commit -m '{GOOD_MESSAGE}'", True, "web/a.test.js 2 -> 1", files=(("web/a.test.js", TWO_SPECS), ("new.txt", "it('a', () => {});\nit.skip('b', () => {});\n")), setup=(BASE, "cp new.txt web/a.test.js && git add -A")),
    kept("a test.skip test counts for nothing", f"git commit -m '{GOOD_MESSAGE}'", True, "web/a.test.js 2 -> 1", files=(("web/a.test.js", TWO_SPECS), ("new.txt", "it('a', () => {});\ntest.skip('b', () => {});\n")), setup=(BASE, "cp new.txt web/a.test.js && git add -A")),
    kept("an xit test counts for nothing", f"git commit -m '{GOOD_MESSAGE}'", True, "web/a.test.js 2 -> 1", files=(("web/a.test.js", TWO_SPECS), ("new.txt", "it('a', () => {});\nxit('b', () => {});\n")), setup=(BASE, "cp new.txt web/a.test.js && git add -A")),
    commit("an attribution inside bash -c is read", "bash -c \"git commit -m 'feat: add y' -m '* did it' -m 'Co-Authored-By: Claude'\"", True, "AI attribution"),
    kept("a test written in a string does not count", f"git commit -m '{GOOD_MESSAGE}'", True, "tests/test_x.py 2 -> 0", files=(*KEPT_FILES, ("new.txt", 'X = """\ndef test_a():\n    assert 1\ndef test_b():\n    assert 1\n"""\n')), setup=(BASE, "cp new.txt tests/test_x.py && git add -A")),
    kept("go tests are counted", f"git commit -m '{GOOD_MESSAGE}'", True, "pkg/a_test.go 2 -> 1", files=(("pkg/a_test.go", "func TestA(t *testing.T) {}\nfunc TestB(t *testing.T) {}\n"),), setup=(BASE, "printf 'func TestA(t *testing.T) {}\\n' > pkg/a_test.go && git add -A")),
    kept("rust tests in a source file are counted", f"git commit -m '{GOOD_MESSAGE}'", True, "src/lib.rs 2 -> 1", files=(("src/lib.rs", "#[test]\nfn a() {}\n#[test]\nfn b() {}\n"),), setup=(BASE, "printf '#[test]\\nfn a() {}\\n' > src/lib.rs && git add -A")),
    kept("a drop under env is judged", f"env git commit -m '{GOOD_MESSAGE}'", True, DROP),
    kept("a drop in bash -c is judged", f"bash -c \"git commit -m '{GOOD_MESSAGE}'\"", True, DROP),
    kept("a drop through git -C is judged from there", f"git -C project commit -m '{GOOD_MESSAGE}'", True, DROP, cwd=""),
    kept("a drop after a cd is judged from there", f"cd project && git commit -m '{GOOD_MESSAGE}'", True, DROP, cwd=""),
)
COMMIT_CASES = (
    *KEPT_CASES,
    commit("a good message passes", f"git commit -m '{GOOD_MESSAGE}'", False),
    commit("a subject with no scope passes", "git commit -m 'fix: keep it\n\n* did it'", False),
    commit("a breaking mark passes", "git commit -m 'feat(x)!: drop it\n\n* did it'", False),
    commit("a heredoc message is read", "git commit -m \"$(cat <<'EOF'\nfeat: add y\n\n* did it\nEOF\n)\"", False),
    commit("a bad heredoc message is refused", "git commit -m \"$(cat <<'EOF'\nadd y\n\n* did it\nEOF\n)\"", True, "not `type(scope)"),
    commit("two -m values join", "git commit -m 'feat: add y' -m '* did it'", False),
    commit("a cluster holds the message option", "git commit -qam 'add y'", True, "not `type(scope)"),
    commit("the long option is read", "git commit --message='add y'", True, "not `type(scope)"),
    commit("a free subject is refused", "git commit -m 'update stuff\n\n* did it'", True, "not `type(scope)"),
    commit("an unknown type is refused", "git commit -m 'wip: thing\n\n* did it'", True, "not `type(scope)"),
    commit("a period is refused", "git commit -m 'feat: add y.\n\n* did it'", True, "ends in a period"),
    commit("no body is refused", "git commit -m 'feat: add y'", True, "needs `* ` bullets"),
    commit("no blank line is refused", "git commit -m 'feat: add y\n* did it'", True, "blank line"),
    commit("a paragraph body is refused", "git commit -m 'feat: add y\n\nI did it.'", True, "needs `* ` bullets"),
    commit("a stray line among bullets is refused", "git commit -m 'feat: add y\n\n* did it\nand more'", True, "no bullet"),
    commit("an indented line continues a bullet", "git commit -m 'feat: add y\n\n* did it\n  and more'", False),
    commit("a footer passes", "git commit -m 'feat: add y\n\n* did it\n\nRefs: #12'", False),
    commit("a Claude trailer is refused", f"git commit -m '{GOOD_MESSAGE}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>'", True, "AI attribution"),
    commit("a generated line is refused", f"git commit -m '{GOOD_MESSAGE}\n\nGenerated with Claude Code'", True, "AI attribution"),
    commit("a robot is refused", f"git commit -m '{GOOD_MESSAGE}\n\n\U0001f916 done'", True, "AI attribution"),
    commit("a person as co-author passes", f"git commit -m '{GOOD_MESSAGE}\n\nCo-Authored-By: A Person'", False),
    commit("a body may name a product", "git commit -m 'docs: explain\n\n* how Claude Code loads hooks'", False),
    commit("a message file is read", "git commit -F msg.txt", True, "not `type(scope)", files=(("msg.txt", "add y\n"),)),
    commit("a good message file passes", "git commit -F msg.txt", False, files=(("msg.txt", f"{GOOD_MESSAGE}\n"),)),
    commit("a missing message file is refused", "git commit -F nope.txt", True, "`nope.txt` does not exist yet"),
    commit("the editor is refused, with the way to pass a message", "git commit", True, "pass it with `-F <file>`"),
    commit("no new message is refused", "git commit --amend --no-edit", True, "git opens an editor"),
    commit("a merge subject passes", "git commit -m 'Merge branch x'", False),
    commit("a fixup passes", "git commit -m 'fixup! feat: add y'", False),
    commit("a commit inside a chain is read", "git add a && git commit -m 'add y'", True, "not `type(scope)"),
    commit("git options before commit are skipped", "git -C /x commit -m 'add y'", True, "not `type(scope)"),
    commit("another git command passes", "git log -m 'add y'", False),
    commit("a pull request with attribution is refused", "gh pr create --title t --body 'x\n\nGenerated with Claude Code'", True, "AI attribution"),
    commit("a plain pull request passes", "gh pr create --title t --body 'free text'", False),
    commit("a pull request heredoc is read", "gh pr create -b \"$(cat <<'EOF'\nCo-Authored-By: Claude\nEOF\n)\"", True, "AI attribution"),
    commit("a trailer in a variable is refused", "T='Co-Authored-By: Claude <noreply@anthropic.com>' && git commit -m \"feat: add y $T\"", True, "AI attribution"),
    commit("an earlier heredoc is not the message", "python3 - <<'EOF'\nprint(1)\nEOF\ngit commit -m \"$(cat <<'EOF'\nfeat: add y\n\n* did it\nEOF\n)\"", False),
    commit("a body that says commit is still read", "git commit -m \"$(cat <<'EOF'\nFix stuff\n\n* split the commit in two\nEOF\n)\"", True, "not `type(scope)"),
    commit("a trailer option is refused", "git commit -m 'feat: add y' -m '* did it' --trailer 'Co-Authored-By: Claude'", True, "AI attribution"),
    commit("a trailer in an earlier script is no attribution", "python3 - <<'EOF'\nprint('Co-Authored-By: Claude')\nEOF\ngit commit -m 'feat: add y' -m '* did it'", False),
    commit("an edited pull request is checked", "gh pr edit 1 --body 'Generated with Claude Code'", True, "AI attribution"),
    commit("a later command naming a tool is no attribution", "git commit -m 'feat: add y' -m '* did it'; rg 'generated with' a; claude plugin list", False),
    commit("a pull request body held in a variable is refused", "T='Generated with Claude Code'; gh pr create --body \"$T\"", True, "AI attribution"),
    commit("an unreadable message does not read later steps", "git commit -m \"$M\"; rg 'generated with claude' a", True, "cannot be read", lacks="AI attribution"),
    commit("env before git is seen through", "env git commit -m 'add y'", True, "not `type(scope)"),
    commit("command before git is seen through", "command git commit -m 'add y'", True, "not `type(scope)"),
    commit("sudo before git is seen through", "sudo git commit -m 'add y'", True, "not `type(scope)"),
    commit("a bash -c commit is read", "bash -c \"git commit -m 'add y'\"", True, "not `type(scope)"),
    commit("a good bash -c commit passes", "bash -c \"git commit -m 'feat: add y' -m '* did it'\"", False),
    commit("an attached message is read", "git commit -m'add y'", True, "not `type(scope)"),
    commit("an attached message in a cluster is read", "git commit -am'add y'", True, "not `type(scope)"),
    commit("a long option prefix is read", "git commit --mess 'add y'", True, "not `type(scope)"),
    commit("a good attached message passes", "git commit -m'feat: add y' -m'* did it'", False),
    commit("a message in a variable is refused", "M='feat: add y'; git commit -m \"$M\"", True, "-F <file>"),
    commit("a substitution with no heredoc is refused", "git commit -m \"$(printf 'feat: add y')\"", True, "-F <file>"),
    commit("a message file written by the same command is refused", "printf 'feat: add y\\n\\n* did it\\n' > m.txt; git commit -F m.txt", True, "written by the same command"),
    commit("stdin with no heredoc is refused", "git commit -F -", True, "reads stdin"),
    commit("a heredoc on stdin is read", "git commit -F - <<'EOF'\nfeat: add y\n\n* did it\nEOF", False),
    commit("a reused message is refused", "git commit -C HEAD", True, "reuses"),
    commit("a fixup with no message passes", "git commit --fixup HEAD", False),
    commit("a message file after a cd is read from there", "cd sub && git commit -F msg.txt", False, files=(("sub/msg.txt", f"{GOOD_MESSAGE}\n"),)),
    commit("a message file after git -C is read from there", "git -C sub commit -F msg.txt", True, "not `type(scope)", files=(("sub/msg.txt", "add y\n"),)),
    commit("a generated-by bullet about code passes", "git commit -m 'feat(x): y' -m '* Stop code generated by the parser from moving the cursor'", False),
    commit("a generated-with bullet about a schema passes", "git commit -m 'feat(x): y' -m '* Add the client generated with the openai schema'", False),
    commit("a generated line with no AI name right after passes", "gh pr create --title t --body 'Generated with the openai schema tool'", False),
    commit("a generated line with a bracket is refused", f"git commit -m '{GOOD_MESSAGE}\n\nGenerated with [Claude Code](https://x)'", True, "AI attribution"),
    commit("a lookalike letter is read as latin", f"git commit -m '{GOOD_MESSAGE}\n\nCo-Authored-By: \u0421laude'", True, "AI attribution"),
    commit("a zero-width space is dropped", f"git commit -m '{GOOD_MESSAGE}\n\nCo-Authored-By: Cl\u200baude'", True, "AI attribution"),
    commit("a full-width name is read by NFKC", f"git commit -m '{GOOD_MESSAGE}\n\nCo-Authored-By: \uff23\uff4c\uff41\uff55\uff44\uff45'", True, "AI attribution"),
    commit("a model name as co-author is refused", f"git commit -m '{GOOD_MESSAGE}\n\nCo-Authored-By: Opus 4'", True, "AI attribution"),
    commit("an Assisted-by trailer is refused", f"git commit -m '{GOOD_MESSAGE}\n\nAssisted-by: Claude'", True, "AI attribution"),
    commit("a Generated-by trailer is refused", f"git commit -m '{GOOD_MESSAGE}\n\nGenerated-by: Sonnet'", True, "AI attribution"),
    commit("a space before the colon is read", f"git commit -m '{GOOD_MESSAGE}\n\nco-authored-by : Claude'", True, "AI attribution"),
    commit("an LLM co-author is refused", f"git commit -m '{GOOD_MESSAGE}\n\nCo-Authored-By: LLM'", True, "AI attribution"),
    commit("a key=value trailer is refused", "git commit -m 'feat: add y' -m '* did it' --trailer 'Co-authored-by=Claude'", True, "AI attribution"),
    commit("an AI author is refused", "git commit -m 'feat: add y' -m '* did it' --author='Claude <noreply@anthropic.com>'", True, "as author"),
    commit("an AI user name is refused", "git -c user.name=Claude commit -m 'feat: add y' -m '* did it'", True, "as author"),
    Case("an unexpected error in the commit rule lets the call run", ("commit_gate.py",), {"tool_name": "Bash", "tool_input": "git commit"}, False, "failed and let the call run", STRICT, is_exit_one=True),
    commit("generated by an AI in the middle of a line passes", "git commit -m 'feat: add y' -m '* keep the stub generated by Claude out of the build'", False),
    commit("a person as author passes", "git commit -m 'feat: add y' -m '* did it' --author='A Person <person>'", False),
    commit("a tag message is read", "git tag -a v1 -m 'Generated with Claude Code'", True, "AI attribution"),
    commit("a merge message is read", "git merge x -m 'Merge x' -m 'Co-Authored-By: Claude'", True, "AI attribution"),
    commit("a plain tag passes", "git tag -a v1 -m 'release 1'", False),
    commit("a pull request title is read", "gh pr create --title 'Generated with Claude' --body x", True, "AI attribution"),
    commit("a pull request body file is read", "gh pr create --title t --body-file b.md", True, "AI attribution", files=(("b.md", "Generated with Claude Code\n"),)),
    commit("a pull request comment is read", "gh pr comment 1 --body 'Generated with Claude Code'", True, "AI attribution"),
    commit("a plain pull request comment passes", "gh pr comment 1 --body 'looks good'", False),
    commit("a sign-off naming an AI is refused", "git commit -m 'feat: add y' -m '* did it' -m 'Signed-off-by: Claude <noreply>'", True, "AI attribution"),
    commit("a sign-off by a person passes", "git commit -m 'feat: add y' -m '* did it' -m 'Signed-off-by: A Person <person>'", False),
    commit("a line made with an AI is refused", "gh pr create --title t --body 'x\n\nMade with Claude Code'", True, "AI attribution"),
    commit("a sign-off by a hyphenated first name passes", "git commit -m 'feat: add y' -m '* did it' -m 'Signed-off-by: Jean-Claude Martin <jc@example.com>'", False),
    commit("a co-author named Ai passes", f"git commit -m '{GOOD_MESSAGE}\n\nCo-authored-by: Ai Tanaka <ai@example.com>'", False),
    commit("a co-author named AI is refused", f"git commit -m '{GOOD_MESSAGE}\n\nCo-authored-by: AI'", True, "AI attribution"),
    commit("a made-with bullet about cursor pagination passes", "git commit -m 'feat: add y' -m '* Made with cursor pagination'", False),
    commit("a made-with line naming Cursor is refused", "gh pr create --title t --body 'x\n\nMade with Cursor'", True, "AI attribution"),
    commit("a made-with line naming Cursor AI is refused", "gh pr create --title t --body 'x\n\nMade with Cursor AI'", True, "AI attribution"),
    commit("a Copilot co-author is refused", f"git commit -m '{GOOD_MESSAGE}\n\nCo-Authored-By: GitHub Copilot'", True, "AI attribution"),
    commit("a GPT-4 co-author is refused", f"git commit -m '{GOOD_MESSAGE}\n\nCo-Authored-By: GPT-4'", True, "AI attribution"),
    commit("a line made with care passes", "gh pr create --title t --body 'Made with care by the team'", False),
    commit("made with an AI in the middle of a line passes", "gh pr create --title t --body 'the stub made with Claude stays out'", False),
    commit("a gh api body field is refused", "gh api repos/o/r/issues/1/comments -f body='Generated with Claude Code'", True, "AI attribution"),
    commit("a gh api typed field is refused", "gh api repos/o/r/pulls -F title=t --field=body='Generated with Claude Code'", True, "AI attribution"),
    commit("a gh api field file is read", "gh api repos/o/r/issues/1/comments -F body=@b.md", True, "AI attribution", files=(("b.md", "Generated with Claude Code\n"),)),
    commit("a gh api field held in a variable is refused", "B='Generated with Claude Code'; gh api repos/o/r/issues/1/comments -f body=\"$B\"", True, "AI attribution"),
    commit("a plain gh api field passes", "gh api repos/o/r/issues/1/comments -f body='looks good'", False),
    commit("a gh api call with no field passes", "gh api repos/o/r/pulls --jq '.[].title'", False),
    commit("dash bullets pass", "git commit -m 'feat: add y\n\n- did it\n- because z'", False),
    commit("the rule can be turned off", "git commit -m 'add y'", False, config={"guard": {"commit_style": False}}),
    commit("no project file still has the commit rule", "git commit -m 'add y'", True, "the subject is not", config=None),
    commit("the commit rule runs in the home folder", "git commit -m 'add y'", True, "the subject is not", config=None, cwd=""),
)












def skill_call(skill: str, /) -> dict:
    return assistant({"type": "tool_use", "id": f"t-{skill}", "name": "Skill", "input": {"skill": skill}})


def skill_lines(*skills: str) -> str:
    return "".join(json.dumps(skill_call(skill)) + "\n" for skill in skills)


def skill_gate(name: str, path: str, is_injected: bool, text: str = "", /, *, agent: str = "", main: tuple[str, ...] = (), **options: object) -> Case:

    gate_config = {"guard": {"scratch": "__scratch__"}, "skill_gate": {"*.py": ["harness:code-python"], "*.css": ["harness:code-html-css"], "docs/*.md": ["write-docs"], "*.md": ["write-md"]}}
    options.setdefault("config", gate_config)
    event = {"tool_name": "Edit", "tool_input": {"file_path": path}, "transcript_path": "transcript.jsonl"}
    if agent:
        event |= {"agent_id": "a1", "transcript_path": "project/s.jsonl"}
        options["files"] = (("s/subagents/agent-a1.jsonl", agent),)
    options.setdefault("transcript", tuple(skill_call(skill) for skill in main))
    event |= options.pop("event", {})

    if is_injected:
        return Case(name, ("skill_gate.py",), event, False, is_unchanged=True, context=text or "Harness skill", **options)

    return Case(name, ("skill_gate.py",), event, False, lacks="Harness skill", is_unchanged=True, **options)


def shell_gate(name: str, command: str, is_injected: bool, text: str = "", /, *, main: tuple[str, ...] = (), **options: object) -> Case:
    return skill_gate(name, "", is_injected, text, main=main, event={"tool_name": "Bash", "tool_input": {"command": command}}, **options)


BIG_BODY = "x" * 6000
PLUG_FILES = tuple((f"plug/skills/{name}/SKILL.md", f"---\nname: {name}\ndescription: d\n---\n{name.upper()[5:]}BODY {BIG_BODY}\n") for name in ("code-python", "code-js"))
PY_JS_CONFIG = {"skill_gate": {"*.py": ["harness:code-python", "harness:code-js"]}}
MARKER_LINE = {"type": "user", "message": {"content": [{"type": "text", "text": "Harness skill text: harness:code-python\n(Reference text)"}]}}
SHELL_CONFIG = {"skill_gate": {"*.sh": ["harness:code-shell"]}}
PADDING = {"type": "user", "message": {"content": "x" * 2200000}}
PY_EDIT = "python3 - <<'EOF'\np = 'src/app.py'\ns = open(p).read()\nopen(p, 'w').write(s)\nEOF"
SKILL_GATE_CASES = (
    shell_gate("a Python edit script of an existing project file needs its skill", PY_EDIT, True, "harness:code-python", files=(("src/app.py", "x\n"),)),
    shell_gate("a write_text script of an existing project file needs its skill", "python3 - <<'EOF'\nPath('a.css').write_text('x')\nEOF", True, "harness:code-html-css", files=(("a.css", "x\n"),)),
    shell_gate("a script writing only under the throwaway folder needs nothing though it names a project file", "python3 - <<'EOF'\nopen('/tmp/harness/project/out.txt', 'w').write(open('src/app.py').read())\nEOF", False, files=(("src/app.py", "x\n"),)),
    shell_gate("a script quoting a project file that does not exist needs nothing", "python3 - <<'EOF'\nopen('src/new.py', 'w').write('x')\nEOF", False),
    shell_gate("a commit needs its skill", "git commit -m 'feat: y'", True, "harness:git"),
    shell_gate("a commit with its skill passes", "git commit -m 'feat: y'", False, main=("harness:git",)),
    shell_gate("a commit deep in a chain needs its skill", "git add a && git -C x commit -m y", True, "harness:git"),
    shell_gate("a pull request needs the skill", "gh pr create --title t", True, "harness:git"),
    shell_gate("git status needs no skill", "git status", False),
    skill_gate("skill gate: a Read of code needs nothing", "app.py", False, event={"tool_name": "Read"}),
    skill_gate("skill gate: an absolute path inside the project is judged", "@ROOT@/project/app.py", True, "editing app.py"),
    shell_gate("a download onto a path with a variable needs nothing", 'curl -sL -o "$d/install.sh" https://x.example/i', False, config=SHELL_CONFIG),
    shell_gate("a download onto a script needs its skill", "curl -sL -o install.sh https://x.example/i", True, "harness:code-shell", config=SHELL_CONFIG),
    shell_gate("a script that only names a pattern needs nothing", "python3 - <<'EOF'\nprint(open('out.txt', 'w').write(str(glob('*.ts'))))\nEOF", False, config={"skill_gate": {"*.ts": ["harness:code-js"]}}),
    shell_gate("a copy onto code needs its skill", "cp x.txt app.py", True, "harness:code-python"),
    shell_gate("a copy of code onto another kind needs nothing", "cp app.py x.txt", False),
    shell_gate("a redirect onto a glob needs nothing", "echo x > *.py", False),
    skill_gate("skill gate: a skill past the tail is given again", "app.py", True, "harness:code-python", transcript=(skill_call("harness:code-python"), PADDING)),
    skill_gate("skill gate: a skill inside the tail counts", "app.py", False, transcript=(PADDING, skill_call("harness:code-python"))),
    shell_gate("a redirect onto code needs its skill", "echo x > app.py", True, "harness:code-python"),
    shell_gate("sed -i on code needs its skill", "sed -i s/a/b/ app.py", True, "harness:code-python", files=(("app.py", ""),)),
    shell_gate("a shell write into scratch needs nothing", "echo x > __scratch__/app.py", False),
    shell_gate("a redirect onto another kind of file needs nothing", "echo x > notes.txt", False),
    shell_gate("a Python edit with its skill passes", PY_EDIT, False, main=("harness:code-python",)),
    shell_gate("a read-only Python script needs nothing", "python3 - <<'EOF'\nprint(open('a.py').read())\nEOF", False),
    shell_gate("a heredoc to cat is no script", "cat <<'EOF'\nopen('a.py', 'w')\nEOF", False),
    shell_gate("a script writing into scratch needs nothing", "python3 - <<'EOF'\nopen('__scratch__/a.py', 'w')\nEOF", False),
    shell_gate("running a script needs nothing", "python3 app.py", False),
    skill_gate("skill gate: an edit with the skill missing gets its text", "app.py", True, "Harness skill text: harness:code-python"),
    skill_gate("skill gate: a prefixed Skill call allows", "app.py", False, main=("harness:code-python",)),
    skill_gate("skill gate: a bare Skill call allows", "app.py", False, main=("code-python",)),
    skill_gate("skill gate: another skill does not count", "app.py", True, main=("code-js",)),
    skill_gate(
        "skill gate: another tool naming a skill does not count",
        "app.py",
        True,
        transcript=(assistant({"type": "text", "text": "Skill"}, {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"skill": "harness:code-python"}}),),
    ),
    skill_gate("skill gate: no project file applies the defaults", "app.py", True, "harness:code-python", config=None),
    skill_gate("skill gate: a test file needs the testing skill with no project file", "tests/test_x.py", True, "harness:testing", config=None, main=("harness:code-python",)),
    skill_gate("skill gate: any file under tests needs the testing skill", "tests/helper.py", True, "harness:testing", config=None, main=("harness:code-python",)),
    skill_gate("skill gate: no key still applies the defaults", "app.py", True, "harness:code-python", config={}),
    skill_gate("skill gate: no project file still applies the defaults", "app.py", True, "harness:code-python", config=None),
    skill_gate("skill gate: scratch is exempt", "__scratch__/t/x.py", False),
    skill_gate("skill gate: an unmatched extension passes", "notes.txt", False),
    skill_gate("skill gate: a path outside the project passes", "@ROOT@/elsewhere/app.py", False),
    skill_gate("skill gate: a nested file matches a bare pattern", "pkg/deep/app.py", True, "pkg/deep/app.py"),
    skill_gate("skill gate: a missing transcript lets the call run", "app.py", False, event={"transcript_path": "missing.jsonl"}),
    skill_gate("skill gate: a broken section falls back to the defaults", "app.py", True, "harness:code-python", config={"skill_gate": ["not", "a map"]}),
    skill_gate("skill gate: a sub-agent reads its own transcript", "app.py", False, agent=skill_lines("harness:code-python")),
    skill_gate("skill gate: a sub-agent does not borrow the session's skill", "app.py", True, "harness:code-python", agent=skill_lines("code-js"), main=("harness:code-python",)),
    skill_gate("skill gate: the main session with an empty transcript gets the text", "app.py", True, "harness:code-python"),
    skill_gate("skill gate: a preloaded skill counts", "app.py", False, agent=json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "<command-message>code-python</command-message>\n<command-name>harness:code-python</command-name>"}]}}) + "\n"),
    skill_gate("skill gate: a slash pattern beats a bare one", "docs/a.md", True, "write-docs"),
    skill_gate("skill gate: the winning pattern's skills are enough", "docs/a.md", False, main=("write-docs",)),
    skill_gate("skill gate: a bare pattern applies outside the slash one", "a.md", True, "write-md"),
    skill_gate("skill gate: every matching bare pattern is required", "app.py", True, "harness:code-html-css", config={"skill_gate": {"*.py": ["harness:code-python"], "app.*": ["harness:code-html-css"]}}, main=("code-python",)),
    skill_gate("skill gate: the union is allowed when both are loaded", "app.py", False, config={"skill_gate": {"*.py": ["harness:code-python"], "app.*": ["harness:code-html-css"]}}, main=("code-python", "harness:code-html-css")),
    skill_gate("skill gate: the skill's own text is given", "app.py", True, "# Python", context_lacks="name: code-python"),
    skill_gate("skill gate: the frontmatter is cut", "app.py", True, "PYTHONBODY", context_lacks="description: d", plugin_root="project/plug", files=PLUG_FILES, config=PY_JS_CONFIG),
    skill_gate("skill gate: a marker in the transcript counts as loaded", "app.py", False, transcript=(MARKER_LINE,)),
    skill_gate("skill gate: a marker in a sub-agent's transcript counts", "app.py", False, agent=json.dumps(MARKER_LINE) + "\n"),
    skill_gate("skill gate: a marker of another skill does not count", "app.py", True, "Harness skill text: harness:code-python", transcript=(MARKER_LINE | {"message": {"content": [{"type": "text", "text": "Harness skill text: harness:code-js\nx"}]}},)),
    skill_gate("skill gate: a note is no marker", "app.py", True, "Harness skill text: harness:code-python", transcript=(MARKER_LINE | {"message": {"content": [{"type": "text", "text": "Harness skill note: harness:code-python applies"}]}},)),
    skill_gate("skill gate: whole skills go in up to the cap, a note for the rest", "app.py", True, "Harness skill note: harness:code-js", context_lacks="Harness skill text: harness:code-js", plugin_root="project/plug", files=PLUG_FILES, config=PY_JS_CONFIG),
    skill_gate("skill gate: the first skill is given whole beside a note", "app.py", True, "Harness skill text: harness:code-python", plugin_root="project/plug", files=PLUG_FILES, config=PY_JS_CONFIG),
    skill_gate("skill gate: a skill the plugin lacks gets a note", "app.py", True, "Harness skill note: harness:code-python", context_lacks="Harness skill text:", plugin_root="project/plug"),
    skill_gate("skill gate: a name with a path is no skill", "app.py", True, "Harness skill note: harness:../x", context_lacks="Harness skill text:", config={"skill_gate": {"*.py": ["harness:../x"]}}),
    *(skill_gate(f"skill gate: {path} needs {skill} by default", path, True, skill, config=None)
      for path, skill in (("q/a.sql", "harness:code-sql"), ("a.yaml", "harness:code-yaml"), ("ci/a.yml", "harness:code-yaml"), ("Makefile", "harness:code-make"), ("sub/GNUmakefile", "harness:code-make"), ("rules.mk", "harness:code-make"))),
    skill_gate("skill gate: one note per missing skill", "app.py", True, "harness:code-html-css", config={"skill_gate": {"*.py": ["harness:code-python", "harness:code-html-css"]}}, main=("code-python",)),
)


def hook_command(name: str, blocks: bool, text: str, /, **options: object) -> Case:
    event = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD~1"}}

    return Case(name, ("hooks.json", "PreToolUse"), event, blocks, text, STRICT, is_silent=not blocks, **options)


COMMAND_CASES = (
    hook_command("hooks.json command: a hook script that exists runs and refuses as before", True, "history"),
    hook_command("hooks.json command: a missing hook script lets the call through, silent", False, "", plugin_root="plug", files=(("../plug/keep", ""),)),
)


DISPATCH_CRASH = (("data/progress/case-session.jsonl", "{}\n"), ("data/progress/case-session.offset/blocked", ""))


def dispatched(name: str, command: str, blocks: bool, text: str = "", /, *, event: dict | None = None, **options: object) -> Case:
    tool_event = {"tool_name": "Bash", "tool_input": {"command": command}, **(event or {})}
    options.setdefault("config", STRICT)

    return Case(name, ("dispatch.py", "PreToolUse"), tool_event, blocks, text, **options)


DISPATCH_CASES = (
    dispatched("dispatcher: a guard refusal still refuses", "git reset --hard HEAD~1", True, "history"),
    dispatched("dispatcher: the commit rule still refuses", "git commit -m 'bad title'", True, "commit rule", git=("git init -q",)),
    dispatched("dispatcher: a changed command and its note arrive together", "uv run pytest -q | tail -5", False, "set -o pipefail", updated={"command": "set -o pipefail; uv run pytest -q | tail -5"}, context="put in front"),
    dispatched("dispatcher: a plain call passes in silence", "ls", False, is_silent=True),
    dispatched("dispatcher: a crashing hook does not stop the guard", "git reset --hard HEAD~1", True, "failed and let the call run", event={"session_id": SESSION}, files=DISPATCH_CRASH),
    dispatched("dispatcher: a crashing hook lets a plain call through", "ls", False, "failed and let the call run", event={"session_id": SESSION}, files=DISPATCH_CRASH),
    Case("dispatcher: the turn hook runs from its event", ("dispatch.py", "Stop"), {"session_id": SESSION}, False, is_silent=True),
)

PIPEFAIL_NOTE = "put in front"


def pipefail(name: str, command: str, fixed: str | None, /, *, agent: bool = False, config: dict | None = STRICT) -> Case:
    tool_input = {"command": command}
    event = {"tool_name": "Bash", "tool_input": tool_input, **({"agent_id": "agent-case1"} if agent else {})}
    if fixed is None:
        return Case(name, ("guard.py",), event, False, config=config, is_unchanged=True, lacks=PIPEFAIL_NOTE)

    return Case(name, ("guard.py",), event, False, "set -o pipefail", config, updated={"command": fixed}, context="put in front")


def kill(name: str, command: str, blocks: bool, /, *, agent: bool = False) -> Case:
    event = {"tool_name": "Bash", "tool_input": {"command": command}, **({"agent_id": "agent-case1"} if agent else {})}
    if blocks:
        return Case(name, ("guard.py",), event, True, "pgrep -x <name>", STRICT)

    return Case(name, ("guard.py",), event, False, config=STRICT, is_unchanged=True)


PIPEFAIL = "set -o pipefail; "
PIPEFAIL_REWRITES = (
    "pytest -q | tail -5",
    "pytest -q 2>&1 | tail -5",
    "pytest -q 2>&1 |tail",
    "pytest | tail -q",
    "python3 -m pytest -x | grep FAIL",
    "uv run pytest tests | grep FAIL",
    "uv run --frozen pytest | tail",
    "uv run python tests/run_cases.py | tail -5",
    "make test | tail",
    "make | tail",
    "uv run ruff check | tail",
    "npm test | tail",
    "pnpm test | tail",
    "yarn run lint | tail",
    "cargo test | tail",
    "cargo build | tail",
    "cargo check | tail",
    "go test ./... | tail",
    "go build ./... | tail",
    "go vet ./... | tail",
    "ruff check . | tail",
    "mypy src | tail",
    "pyright | tail",
    "terraform validate | grep Error",
    "terraform plan | tail",
    "dbt test --target dev | tail",
    "gradle test | tail",
    "mvn test | tail",
    "cd src && pytest -q | tail",
    "FOO=1 pytest | tail",
    "pytest | /usr/bin/tail",
)
PIPEFAIL_UNCHANGED = (
    "pytest |& head",
    "python -m pytest | head",
    "npm run build | head",
    "tsc --noEmit | head",
    "pytest | head -5",
    "pytest | grep -q passed",
    "pytest | grep -m 1 passed",
    "pytest | grep -l passed",
    "pytest | grep -L passed",
    "pytest | grep -iq passed",
    "pytest | grep --quiet passed",
    "pytest | grep passed -m1",
    "rg x | head",
    "cat f | head",
    "git log | head",
    "ls | grep py",
    "pytest -q",
    "pytest -q > out.txt; tail out.txt",
    "pytest | wc -l",
    "pytest || tail",
    "pytest && tail f",
    "set -o pipefail; pytest | tail",
    "bash -o pipefail -c 'pytest | tail'",
    "echo pytest | tail",
    "npm ls | tail",
    "cargo fmt | tail",
    "go mod tidy | tail",
    "terraform fmt | tail",
    "terraform show | tail",
    "uv run python script.py | tail",
    "python tests/run_cases.py | tail",
    "sh -c 'cd src; pytest | tail -5'",
)
PIPEFAIL_CASES = (
    *(pipefail(f"pipefail is set before {command!r}", command, PIPEFAIL + command) for command in PIPEFAIL_REWRITES),
    *(pipefail(f"pipefail is not set before {command!r}", command, None) for command in PIPEFAIL_UNCHANGED),
    pipefail("a sub-agent's check pipe gets pipefail too", "pytest | tail", PIPEFAIL + "pytest | tail", agent=True, config=None),
    pipefail("a sub-agent's plain read keeps no pipefail", "rg x | head", None, agent=True, config=None),
    pipefail("pipefail is set with no project file", "pytest | tail", PIPEFAIL + "pytest | tail", config=None),
    pipefail("a heredoc body is no command", "cat <<'EOF'\npytest | tail\nEOF", None),
)
KILL_REFUSED = (
    "pkill -f cat",
    "pkill cat",
    "pkill -9 cat",
    "pkill -9f cat",
    "pkill --full cat",
    "pkill -fx cat",
    "pkill -u me node",
    "pkill -ux me node",
    "pkill -TERM node",
    "killall -r 'x.*'",
    "killall --regexp x",
    "killall -qr x",
    "sudo pkill -f x",
    "sudo -u root pkill node",
    "env FOO=1 pkill node",
    "nohup pkill -f x",
    "sh -c 'pkill -f x'",
    "bash -c 'sudo killall -r x'",
    "echo a; pkill node",
    "pgrep node && pkill node",
)
KILL_RUNS = (
    "pkill -x node",
    "pkill -9 -x node",
    "pkill -x -9 node",
    "pkill -KILL -x node",
    "pkill --exact node",
    "pkill -u me -x node",
    "sudo pkill -x node",
    "sh -c 'pkill -x node'",
    "kill 123",
    "kill -9 123",
    "pgrep -x node",
    "pgrep -af cat",
    "killall node",
    "killall -9 node",
    "killall -e node",
    "echo pkill -f cat",
    "pkill --help",
    "grep -r pkill .",
)
NESTED_SUBSTITUTIONS = "echo a\n" + "echo $( ` \n" * 300
UNCLOSED_SUBSTITUTIONS = "echo a\n" + "echo $(\n" * 240
DELETE_ESCAPE_CASES = (
    bash("a delete over ssh is refused", "ssh host rm x", True, DELETE),
    bash("a quoted delete over ssh is refused", 'ssh host "rm -rf /srv/x"', True, DELETE),
    agent_bash("a sub-agent's delete over ssh is refused with its own message", "ssh host rm x", True, AGENT_DELETE, config=STRICT),
    bash("a read over ssh runs", "ssh host ls x", False),
    bash("busybox rm is refused", "busybox rm x", True, DELETE),
    bash("busybox ls runs", "busybox ls x", False),
    bash("a variable set to rm is refused as the command", "X=rm; $X x", True, DELETE),
    bash("a braced variable set to rm is refused as the command", "X=rm; ${X} -rf y", True, DELETE),
    bash("a quoted variable set to rm is refused as the command", 'X=rm; "$X" x', True, DELETE),
    bash("a substitution naming rm is refused as the command", "$(echo rm) x", True, DELETE),
    bash("a variable set to ls runs as the command", "X=ls; $X x", False),
    bash("python -c with os.remove is refused", "python3 -c \"import os; os.remove('a')\"", True, DELETE),
    bash("python -c with os.unlink is refused", "python3 -c \"import os; os.unlink('a')\"", True, DELETE),
    bash("python -c with os.rmdir is refused", "python3 -c \"import os; os.rmdir('a')\"", True, DELETE),
    bash("python -c with shutil.rmtree is refused", "python3 -c \"import shutil; shutil.rmtree('a')\"", True, DELETE),
    bash("python -c with Path.unlink is refused", "python3 -c \"from pathlib import Path; Path('a').unlink()\"", True, DELETE),
    bash("python -c with Path.rmdir is refused", "python3 -c \"from pathlib import Path; Path('a').rmdir()\"", True, DELETE),
    bash("a python heredoc with shutil.rmtree is refused", "python3 - <<'EOF'\nimport shutil\nshutil.rmtree('d')\nEOF", True, DELETE),
    bash("a uv run python heredoc with os.remove is refused", "uv run python - <<'EOF'\nimport os\nos.remove('d')\nEOF", True, DELETE),
    agent_bash("a sub-agent's python delete is refused with its own message", "python3 -c \"import os; os.remove('a')\"", True, AGENT_DELETE, config=STRICT),
    bash("python -c without a delete runs", "python3 -c \"print(1)\"", False),
    bash("a python heredoc without a delete runs", "python3 - <<'EOF'\nprint(1)\nEOF", False),
    bash("a delete word in a heredoc of another command runs", "cat <<'EOF'\nos.remove('a')\nEOF", False),
    bash("truncate is refused", "truncate -s 0 a.py", True, DELETE),
    bash("truncate --help runs", "truncate --help", False),
    bash("make clean is refused", "make clean", True, DELETE),
    bash("make distclean is refused", "make distclean", True, DELETE),
    bash("make clean in another folder is refused", "make -C sub clean", True, DELETE),
    bash("make with a folder starting in n is refused", "make -Cnode clean", True, DELETE),
    bash("make build runs", "make build", False),
    bash("make clean as a dry run runs", "make -n clean", False),
    bash("make clean as a dry run in a letter cluster runs", "make -nB clean", False),
    bash("make clean as a long dry run runs", "make --just-print clean", False),
    bash("rm --help runs", "rm --help", False),
    bash("rm --version runs", "rm --version", False),
    bash("rm with a long option that is no help is refused", "rm --force x", True, DELETE),
    bash("git clean -nfd is a dry run and runs", "git clean -nfd", False),
    bash("git clean -fdn is a dry run and runs", "git clean -fdn", False),
    bash("git clean --dry -fd is a dry run and runs", "git clean --dry -fd", False),
    bash("git clean after global options as a dry run runs", "git -C sub clean -nd", False),
    bash("git clean -fdx is refused", "git clean -fdx", True, DELETE),
    bash("git clean with a pattern holding n is refused", "git clean -fdenode", True, DELETE),
    bash("git clean with -n after the paths separator is refused", "git clean -fd -- -n", True, DELETE),
    bash("300 lines of nested substitutions are read in under a second", NESTED_SUBSTITUTIONS, False, max_seconds=1.0),
    bash("240 lines of unclosed substitutions are read in under a second", UNCLOSED_SUBSTITUTIONS, False, max_seconds=1.0),
    bash("a delete past the nesting bound is still refused", "echo " + "$(" * 20 + "x" + ")" * 20 + "; rm y", True, DELETE),
)
KILL_CASES = (
    *(kill(f"{command!r} is refused", command, True) for command in KILL_REFUSED),
    *(kill(f"{command!r} runs", command, False) for command in KILL_RUNS),
    kill("a sub-agent's broad pkill is refused", "pkill -f cat", True, agent=True),
    kill("a sub-agent's pkill -x runs", "pkill -x node", False, agent=True),
)








OWNERSHIP_LINE = "This codebase is yours: what it is for and how it is built are your call, and you will keep building on it."
OWNERSHIP_CASES = (
    context("a session start says the codebase is the model's", {"hook_event_name": "SessionStart"}, OWNERSHIP_LINE),
    context("a sub-agent start does not say it", {"hook_event_name": "SubagentStart", "agent_type": "harness:worker"}, lacks="This codebase is yours"),
    context("a session event carrying an agent id gets no ownership line", {"hook_event_name": "SessionStart", "agent_id": "a1"}, lacks="This codebase is yours"),
    context("a helper start does not say it", {"hook_event_name": "SubagentStart", "agent_type": "Explore"}, lacks="This codebase is yours"),
)


def resolve(root: Path, name: str, /) -> Path:

    if name.startswith("state/"):
        return root / name

    return root / "data" / name[5:] if name.startswith("data/") else root / "project" / name


def is_blocked(run: subprocess.CompletedProcess[str], /) -> bool:

    if run.returncode == 2:
        return bool(run.stderr.strip()) and "Traceback" not in run.stderr
    try:
        output = json.loads(run.stdout)
        return output.get("decision") == "block" or output.get("hookSpecificOutput", {}).get("permissionDecision") == "ask"
    except ValueError:
        return False


def check_output(case: Case, run: subprocess.CompletedProcess[str], root: Path, /) -> str:

    if case.updated is None and not case.is_unchanged and not case.context and not case.context_lacks:
        return ""
    if run.returncode != 0:
        return f"a soft rule must exit 0, got {run.returncode}"
    try:
        output = json.loads(run.stdout).get("hookSpecificOutput", {}) if run.stdout.strip() else {}
    except ValueError:
        return f"the output is no JSON: {run.stdout.strip()[:200]!r}"
    if "permissionDecision" in output:
        return f"a soft rule must carry no permissionDecision: {output['permissionDecision']!r}"
    if case.is_unchanged and "updatedInput" in output:
        return f"the call must run unchanged, got {output['updatedInput']!r}"
    expected = json.loads(json.dumps(case.updated).replace(ROOT, str(root))) if case.updated is not None else None
    if expected is not None and output.get("updatedInput") != expected:
        return f"updatedInput is {output.get('updatedInput')!r}, expected {expected!r}"
    note = output.get("additionalContext", "")
    context = case.context.replace(ROOT, str(root))
    if context and context not in note:
        return f"additionalContext lacks {context!r}: {note[:200]!r}"
    if case.context_lacks and case.context_lacks.replace(ROOT, str(root)) in note:
        return f"additionalContext holds {case.context_lacks!r}"

    return ""


def check_files(case: Case, root: Path, /) -> str:
    leftovers = [path.name for path in root.rglob(".*.tmp")]
    if leftovers:
        return f"a temporary file of write_atomic was left behind: {leftovers}"
    if case.wrote is not None:
        path = resolve(root, case.wrote[0])
        if not path.exists() or case.wrote[1] not in path.read_text():
            return f"{case.wrote[0]} lacks {case.wrote[1]!r}"
    if case.not_wrote is not None:
        path = resolve(root, case.not_wrote[0])
        if path.exists() and case.not_wrote[1] in path.read_text():
            return f"{case.not_wrote[0]} holds {case.not_wrote[1]!r}"

    return ""


def get_hook_command(hooks: Path, name: str, /) -> str:

    events = json.loads((hooks / "hooks.json").read_text())["hooks"]
    commands = [hook["command"] for groups in events.values() for group in groups for hook in group["hooks"] if f'hooks/dispatch.py" {name}' in hook["command"]]
    assert commands, name

    return commands[0]


def run_hook(hooks: Path, script: tuple[str, ...], event: dict, environment: dict[str, str], root: Path, /, *, folder: Path | None = None) -> subprocess.CompletedProcess[str]:

    paths = {key: str(root / event[key]) for key in ("transcript_path", "agent_transcript_path") if key in event}

    command = ["uv", "run", "--script", str(hooks / script[0]), *script[1:]]
    if script[0] == "hooks.json":
        command = ["sh", "-c", get_hook_command(hooks, script[1])]
    try:
        return subprocess.run(
            command,
            input=json.dumps({**event, **paths}).replace(ROOT, str(root)),
            capture_output=True,
            text=True,
            env=environment,
            cwd=folder,
            timeout=HOOK_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", f"the hook hung past {HOOK_TIMEOUT} s")


def run_case(case: Case, hooks: Path, /) -> str:

    WORK.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK) as directory:
        root = Path(directory).resolve()
        project = root / "project"
        (project / "__scratch__" / "t").mkdir(parents=True)
        (root / "data").mkdir()
        (project / "AGENTS.md").write_text("rules\n")
        if case.config is not None:
            (root / "data" / "user.json").write_text(json.dumps(case.config))
        for name, text in case.files:
            path = resolve(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text.replace(ROOT, str(root)))
        for command in case.git:
            subprocess.run(command, shell=True, cwd=project, check=True, capture_output=True, env={**os.environ, "HOME": str(root), **GIT_IDENTITY})
        for name, target in case.links:
            (root / name).symlink_to(root / target)
        for name in (case.cwd, case.project_dir, case.home):
            if name:
                (root / name).mkdir(parents=True, exist_ok=True)
        (root / "transcript.jsonl").write_text("".join(f"{json.dumps(line)}\n" for line in case.transcript).replace(ROOT, str(root)))
        environment = {**os.environ, "CLAUDE_PLUGIN_DATA": str(root / "data"), "CLAUDE_PLUGIN_ROOT": str(Path(__file__).resolve().parent.parent), "HOME": str(root / case.home), "XDG_STATE_HOME": str(root / "state"), "UV_CACHE_DIR": UV_CACHE, "HARNESS_CONFIG": str(root / "data" / "user.json")}
        environment.pop("CLAUDE_PROJECT_DIR", None)
        if case.script[0] == "hooks.json":
            environment["CLAUDE_PLUGIN_ROOT"] = str(hooks.parent)
        if case.plugin_root:
            environment["CLAUDE_PLUGIN_ROOT"] = str(root / case.plugin_root)
        environment["SHELL"] = case.shell
        if case.project_dir:
            environment["CLAUDE_PROJECT_DIR"] = str(root / case.project_dir)
        for script, event in case.before:
            run_hook(hooks, script, {"cwd": str(root / case.cwd), **event}, environment, root)
        if not (hooks / case.script[0]).is_file():
            return f"the hook is missing: {case.script[0]}"
        started = time.monotonic()
        run = run_hook(hooks, case.script, {"cwd": str(root / case.cwd), **case.event}, environment, root, folder=root / case.start if case.start else None)
        elapsed = time.monotonic() - started
        message = run.stderr + run.stdout
        if case.max_seconds and elapsed > case.max_seconds:
            return f"the hook took {elapsed:.2f} s, over the {case.max_seconds} s bound"
        if case.is_exit_one:
            if run.returncode != 1:
                return f"expected exit 1, got {run.returncode}"
        elif run.returncode not in (0, 2):
            return f"the hook crashed, exit {run.returncode}: {message.strip()[-300:]!r}"
        elif is_blocked(run) != case.blocks:
            return f"expected blocks={case.blocks}, got {is_blocked(run)}: {message.strip()[:200]!r}"
        if case.is_silent and (run.returncode != 0 or run.stdout or run.stderr):
            return f"expected exit 0 and no output, got {run.returncode}: {message.strip()[:200]!r}"
        text, lacks = case.text.replace(ROOT, str(root)), case.lacks.replace(ROOT, str(root))
        if text and text not in message:
            return f"the message lacks {text!r}: {message.strip()[:200]!r}"
        if lacks and lacks in message:
            return f"the message holds {lacks!r}: {message.strip()[:200]!r}"

        return check_output(case, run, root) or check_files(case, root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the hook cases: what the guard refuses, when a report goes back, when the Stop hook holds a turn, and what the context hook says.")
    parser.add_argument("--only", default="", help="run the cases whose name holds this text")
    parser.add_argument("--hooks", type=Path, default=HOOKS, help="the hooks folder to judge")
    parser.add_argument("--threads", type=int, default=JOBS, help="cases at once")
    arguments = parser.parse_args()
    every = [*COMMIT_CASES, *GUARD_CASES, *SECRET_CASES, *GATE_CASES, *RESEND_CASES, *TURN_CASES, *BUDGET_CASES, *PROGRESS_CASES, *SKILL_GATE_CASES, *TOOL_CASES, *CONTEXT_CASES, *COMMAND_CASES, *DISPATCH_CASES, *PIPEFAIL_CASES, *DELETE_ESCAPE_CASES, *KILL_CASES, *OWNERSHIP_CASES]
    cases = [case for case in every if arguments.only in case.name]
    failures = 0
    with ThreadPoolExecutor(arguments.threads) as pool:
        for case, reason in zip(cases, pool.map(lambda case: run_case(case, arguments.hooks), cases)):
            failures += bool(reason)
            print(f"FAIL {case.name}: {reason}" if reason else f"ok   {case.name}", flush=True)
    print(f"{len(cases)} cases, {failures} failed")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

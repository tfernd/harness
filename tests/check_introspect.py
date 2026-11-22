#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "introspect.py"
SCRATCH = Path(tempfile.gettempdir()) / "harness" / "harness"
GUARD_TEXT = "Blocked by the harness guard: project files change through the Edit and Write tools. A shell redirect is refused."
ID_TEXT = "Blocked by the harness guard (rule: redirect): project files change through the Edit and Write tools. A shell redirect is refused."
SEARCH_CHARS = 40
COMMIT_TEXT = "Blocked by the harness commit rule (`harness:git`): the subject is too long"
SENDBACK_TEXT = "Your report breaks the report skill's form in these sections only:\n- Answer: missing: Answer\n- Verdict: missing: Verdict\nSend again."
PLUGIN_PATH = "uv run --script /x/.claude/plugins/cache/harness/harness/abc123def456/hooks/guard.py"


def stamp(days_ago: float, /) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def make_call(call_id: str, command: str, days_ago: float, /) -> dict:
    return {"type": "assistant", "timestamp": stamp(days_ago), "sessionId": "s1", "message": {"content": [{"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}]}}


def make_refusal(call_id: str, text: str, days_ago: float, /) -> dict:
    return {"type": "user", "timestamp": stamp(days_ago), "sessionId": "s1", "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "is_error": True, "content": f"PreToolUse:Bash hook error: [{PLUGIN_PATH}]: {text}"}]}}


def make_hook_block(hook_name: str, text: str, agent_id: str | None, days_ago: float, /) -> dict:
    entry = {"type": "attachment", "timestamp": stamp(days_ago), "sessionId": "s1", "attachment": {"type": "hook_blocking_error", "hookName": hook_name, "blockingError": {"blockingError": text}}}
    if agent_id:
        entry["agentId"] = agent_id
        entry["isSidechain"] = True
    return entry


def make_tool_call(call_id: str, name: str, tool_input: dict, days_ago: float, /) -> dict:
    return {"type": "assistant", "timestamp": stamp(days_ago), "sessionId": "s1", "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}]}}


def build_rhythm_project(root: Path, /) -> None:
    slug = "".join(char if char.isalnum() else "-" for char in str(root / "proj"))
    folder = root / "claude" / "projects" / slug
    edits = [make_tool_call(f"e{number}", "Write", {"file_path": f"/work/src/f{number}.py", "content": "x"}, 1) for number in range(3)]
    scratch = make_tool_call("scratch", "Write", {"file_path": "/tmp/harness/proj/probe.py", "content": "x"}, 1)
    same_call = make_call("same", "python3 - <<'EOF' &&\nfrom pathlib import Path\nPath('src/a.py').write_text('x')\nEOF\nmake check", 1)
    sub = edits + [scratch, make_call("k1", "make check", 1), make_call("k2", "uv run pytest -q", 1), same_call]
    write_lines(folder / "main" / "subagents" / "agent-agentrhythm.jsonl", sub)


def write_lines(path: Path, entries: list[dict], /) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")


def run_script(root: Path, /) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT), "--project-dir", str(root / "proj"), "--claude-dir", str(root / "claude"), "--state-dir", str(root / "state"), "--days", "7"]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def make_root() -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(dir=SCRATCH, prefix="introspect-"))
    (root / "proj").mkdir()
    return root


def build_busy_project(root: Path, /) -> None:
    slug = "".join(char if char.isalnum() else "-" for char in str(root / "proj"))
    folder = root / "claude" / "projects" / slug
    main = [make_call("c1", "echo a > out.txt", 1), make_refusal("c1", GUARD_TEXT, 1), make_call("c2", "echo a > out.txt;", 1), make_call("c3", "git commit -m long", 1), make_refusal("c3", COMMIT_TEXT, 1)]
    main += [make_call("n1", "echo n > new1.txt", 1), make_refusal("n1", ID_TEXT, 1), make_call("n1b", "echo n > new1.txt;", 1), make_call("n2", "echo m > new2.txt", 1), make_refusal("n2", ID_TEXT, 1), make_call("n2b", "echo m > new2.txt;", 1)]
    main += [make_hook_block("Stop", "This turn ends with open checks:\n- the closing message needs the job status", None, 1), make_call("old", "echo old > o.txt", 30), make_refusal("old", GUARD_TEXT, 30)]
    write_lines(folder / "main.jsonl", main)
    sub = []
    for number in range(3):
        sub += [make_call(f"s{number}", f"echo {number} > f{number}.txt", 1), make_refusal(f"s{number}", GUARD_TEXT, 1), make_call(f"t{number}", f"echo {number} > f{number}.txt;", 1)]
    sub += [make_hook_block("SubagentStop", SENDBACK_TEXT, "agent1234abcd", 1)]
    write_lines(folder / "main" / "subagents" / "agent-agent1234abcd.jsonl", sub)
    write_lines(folder / "main" / "subagents" / "agent-agent5678efgh.jsonl", [make_hook_block("SubagentStop", SENDBACK_TEXT, "agent5678efgh", 1) for _ in range(4)])
    reports = root / "state" / "proj" / "reports"
    reports.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body = "# Report\n## Problems\n- the guard refused a heredoc (cause: rule)\n- I misread the brief (cause: the agent itself)\n- the loader crashed on a null column (cause: tool)\n\n## Feedback\n- `hooks/guard.py`: name the rule in the message\n- `src/model.py`: rename the loader\n"
    (reports / f"{today}-0100-worker-x.md").write_text(body)
    (reports / "2020-01-01-0100-worker-old.md").write_text("## Feedback\n- `old.py`: stale\n")
    installed = root / "claude" / "plugins"
    installed.mkdir(parents=True)
    (installed / "installed_plugins.json").write_text(json.dumps({"plugins": {"harness@harness": [{"version": "999999aaaaaa"}]}}))


def build_logged_project(root: Path, /) -> None:
    folder = root / "state" / "proj"
    folder.mkdir(parents=True)
    now = datetime.now(timezone.utc).astimezone()
    old = now - timedelta(days=30)
    rows = [{"time": now.strftime("%Y-%m-%dT%H:%M:%S%z"), "rule": "delete", "role": "main", "text": "rm a"}, {"time": now.strftime("%Y-%m-%dT%H:%M:%S%z"), "rule": "delete", "role": "sub-agent", "text": "rm b"}]
    rows += [{"time": old.strftime("%Y-%m-%dT%H:%M:%S%z"), "rule": "wait", "role": "main", "text": "echo old"}]
    (folder / "refusals.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\nnot json\n")


def check(name: str, condition: bool, output: str, /) -> int:
    if condition:
        return 0
    print(f"FAIL {name}\n{output}")
    return 1


def main() -> int:
    failures = 0
    busy = make_root()
    build_busy_project(busy)
    result = run_script(busy)
    out = result.stdout
    failures += check("busy exits 0", result.returncode == 0, result.stderr)
    failures += check("guard rule split main and sub-agent", "4 x project files change through the Edit and Write tools  (main 1, sub-agent 3)" in out, out)
    failures += check("old refusal outside the window is not counted", "guard and commit refusals: 7" in out, out)
    failures += check("commit rule counted", "1 x commit rule: the subject is too long  (main 1, sub-agent 0)" in out, out)
    failures += check("samples are the refused calls", "e.g. echo 0 > f0.txt" in out, out)
    failures += check("repeat of one rule in one transcript is friction", "main: 3 x project files change" in out or "agent-ag: 3 x project files change" in out, out)
    failures += check("retries over the threshold are friction", "4 refusals of project files change through the Edit and Write tools followed by a near-identical retry" in out, out)
    failures += check("retries under the threshold are not listed", "1 refusals" not in out and "2 refusals" not in out, out)
    failures += check("a rule id is the group key", "2 x redirect  (main 2, sub-agent 0)" in out, out)
    failures += check("an old refusal gets a plain search pattern", "old format, search for: " + "project files change through the Edit and Write tools"[:SEARCH_CHARS] in out, out)
    failures += check("a new refusal gets no search pattern", out.count("old format, search for") == 1, out)
    failures += check("samples name the transcript and the agent", "e.g. echo 0 > f0.txt  [transcript main, agent agent123]" in out and "e.g. echo n > new1.txt  [transcript main]" in out, out)
    failures += check("a repeated send-back is gate friction", "gate friction: agent agent567: 4 times" not in out and "gate friction: agent agent567 was sent back 4 times" in out, out)
    failures += check("a single send-back is no gate friction", "gate friction: agent agent123" not in out, out)
    failures += check("transcripts are the source without a log", "source: transcripts only" in out, out)
    failures += check("project report items are counted, not shown", "project items (not shown): 2" in out and "loader" not in out, out)
    failures += check("send-back per agent with sections", "agent agent123: 1 x, missing Answer, Verdict" in out, out)
    failures += check("stop gate of the main session", "1 x - the closing message needs the job status" in out, out)
    failures += check("problem with an outside cause listed", "the guard refused a heredoc (cause: rule)" in out, out)
    failures += check("problem caused by the agent itself dropped", "I misread the brief" not in out, out)
    failures += check("feedback listed, old report dropped", "name the rule in the message" in out and "stale" not in out, out)
    failures += check("version loaded and installed differ", "installed: 999999aaaaaa" in out and "loaded abc123def456  (not the installed one)" in out, out)
    rhythm = make_root()
    build_rhythm_project(rhythm)
    result = run_script(rhythm)
    failures += check("check rhythm of a sub-agent: edits per check, share after few edits, same-call share", "sub-agent: 4 edits, 3 checks, 1.33 edits per check, 66% of checks after one or no edits, 33% in the same call as an edit, 0 of 1 editing agents with 4 or more checks" in result.stdout, result.stdout + result.stderr)
    failures += check("check rhythm names a main session with no checks", "main session: 0 edits, no checks" in result.stdout, result.stdout)
    logged = make_root()
    build_logged_project(logged)
    result = run_script(logged)
    failures += check("a refusal log is read and named as the source", "source: refusal log refusals.jsonl" in result.stdout and "2 x delete  (main 1, sub-agent 1)" in result.stdout and "echo old" not in result.stdout, result.stdout + result.stderr)
    empty = make_root()
    result = run_script(empty)
    failures += check("empty project says nothing found and exits 0", result.returncode == 0 and "nothing found" in result.stdout, result.stdout + result.stderr)
    print("introspect checks: ok" if not failures else f"introspect checks: {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

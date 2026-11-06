"""Check bin/compaction-report on a small synthetic log folder with known numbers.

Builds the logs under a temp folder, runs the tool as a subprocess and asserts the exact logged cost, the replay check,
falling compaction counts, the named excluded model, the date window and the absence of home paths.
Set COMPACTION_TOOL to point at another copy of the tool (used to show a planted bug fails).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = Path(os.environ.get("COMPACTION_TOOL", ROOT / "bin" / "compaction-report"))
PRICED = "claude-sonnet-5-5"
UNPRICED = "claude-mystery-9"
HOME_PREFIX = "/".join(("", "home", ""))
# (timestamp, input, cache read, cache write, output) of the five main-session calls.
MAIN_CALLS = [
    ("2026-10-01T10:00:00Z", 10, 0, 40000, 1000),
    ("2026-10-01T10:01:00Z", 5, 40000, 2000, 500),
    ("2026-10-01T10:02:00Z", 5, 42000, 3000, 400),
    ("2026-10-01T10:04:00Z", 5, 30000, 9000, 300),
    ("2026-10-02T09:00:00Z", 5, 39000, 1000, 200),
]
# Dollars worked by hand at $2 input, $10 output, $0.20 cache read, $2.50 cache write per million tokens.
EXPECTED_ALL = 0.19176
EXPECTED_LAST_DAY = 0.01231


def make_call(name: str, model: str, usage: tuple[str, int, int, int, int]) -> str:
    """One assistant log line."""
    timestamp, inp, read, write, out = usage
    usage_data = {
        "input_tokens": inp,
        "cache_read_input_tokens": read,
        "cache_creation_input_tokens": write,
        "output_tokens": out,
    }
    message = {"id": name, "model": model, "role": "assistant", "usage": usage_data}
    return json.dumps({"type": "assistant", "timestamp": timestamp, "message": message}, separators=(",", ":"))


def make_logs(root: Path) -> None:
    """Write the synthetic folder: a main session with one compaction, a sub-agent run and an unpriced model."""
    project = root / "project-one"
    (project / "session" / "subagents").mkdir(parents=True)
    boundary = {
        "type": "system",
        "subtype": "compact_boundary",
        "timestamp": "2026-10-01T10:03:00Z",
        "compactMetadata": {"trigger": "auto", "preTokens": 45000, "postTokens": 8000},
    }
    lines = [make_call(f"m{i}", PRICED, call) for i, call in enumerate(MAIN_CALLS)]
    lines.insert(3, json.dumps(boundary, separators=(",", ":")))
    (project / "main.jsonl").write_text("\n".join(lines) + "\n")
    sub_lines = [make_call(f"s{i}", PRICED, (f"2026-10-01T11:0{i}:00Z", 5, 20000 * i, 20000, 100)) for i in range(2)]
    (project / "session" / "subagents" / "agent-one.jsonl").write_text("\n".join(sub_lines) + "\n")
    other = [make_call(f"x{i}", UNPRICED, (f"2026-10-01T12:0{i}:00Z", 5, 0, 1000, 10)) for i in range(2)]
    (project / "other.jsonl").write_text("\n".join(other) + "\n")


def run_tool(root: Path, out: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Run the tool with a clean environment for the log folder."""
    env = {key: value for key, value in os.environ.items() if key != "CLAUDE_CONFIG_DIR"}
    return subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root), "--out", str(out), *extra], capture_output=True, text=True, env=env
    )


def main() -> int:
    """Run every case; print the first failure and exit 1."""
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        make_logs(base / "logs")
        full = run_tool(base / "logs", base / "all")
        assert full.returncode == 0, full.stderr
        data = json.loads((base / "all" / "data.json").read_text())
        page = (base / "all" / "report.html").read_text()

        main_set = data["sets"]["main"]
        assert abs(main_set["observed"]["total"] - EXPECTED_ALL) < 1e-9, main_set["observed"]["total"]
        assert main_set["compactions"]["count"] == 1
        assert abs(main_set["check"]["percent_error"]) < main_set["check"]["tolerance"], main_set["check"]
        counts = [main_set["thresholds"][str(t)]["cost"]["num_compactions"] for t in data["thresholds"]]
        assert counts == sorted(counts, reverse=True) and counts[0] > counts[-1], counts
        assert data["excluded_models"] == [UNPRICED] and UNPRICED in page
        for text in (page, json.dumps(data)):
            assert str(Path.home()) not in text and HOME_PREFIX not in text and str(base) not in text

        window = run_tool(base / "logs", base / "day", "--since", "2026-10-02")
        assert window.returncode == 0, window.stderr
        day = json.loads((base / "day" / "data.json").read_text())["sets"]["main"]
        assert day["num_calls"] == 1 and abs(day["observed"]["total"] - EXPECTED_LAST_DAY) < 1e-9, day["observed"]

        (base / "empty").mkdir()
        none = run_tool(base / "empty", base / "none")
        assert none.returncode == 1 and "Traceback" not in none.stderr and none.stderr.strip(), none.stderr
    print("compaction report checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

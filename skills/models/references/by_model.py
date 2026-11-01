# /// script
# requires-python = ">=3.10"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""Self-scores per role and model from a ledger, with the model read from each agent's transcript.

Usage: uv run --script by_model.py LEDGER.jsonl TRANSCRIPT_ROOT [PROJECT]

LEDGER.jsonl: rows written by `bin/harness-import` or `hooks/report_gate.py`.
TRANSCRIPT_ROOT: the folder holding `*/subagents/agent-<agent_id>.meta.json`, for example
    ~/.claude/projects/<project folder>.
PROJECT: keep only rows whose `project` equals it (default: every row).
Groups with fewer than MIN_N reports are not printed, since a measured claim under 10 samples is dropped
(`harness:models`).
"""

import collections
import glob
import json
import re
import sys

MIN_N = 10
MODEL_IDS = {
    "claude-haiku-5-5": "haiku",
    "claude-sonnet-5-5": "sonnet",
    "claude-opus-5-5": "opus",
}


def model_of(meta_path: str, meta: dict) -> str:
    """The model from the `.meta.json`, else the last `model` field of the transcript beside it."""
    if meta.get("model"):
        return meta["model"]
    transcript = meta_path.replace(".meta.json", ".jsonl")
    text = open(transcript, errors="replace").read()
    found = re.findall(r'"model": ?"(claude-[a-z0-9-]+)"', text)
    last = found[-1] if found else "unknown"
    return MODEL_IDS.get(last, last)


def main(ledger: str, root: str, project: str | None) -> None:
    rows = [json.loads(line) for line in open(ledger, errors="replace") if line.strip()]
    groups = collections.defaultdict(
        lambda: {"n": 0, "scores": collections.defaultdict(list), "causes": collections.Counter(), "noprob": 0}
    )
    for row in rows:
        if project and row["project"] != project:
            continue
        paths = glob.glob(f"{root}/*/subagents/agent-{row['agent_id']}.meta.json")
        meta = json.load(open(paths[0])) if paths else {}
        model = model_of(paths[0], meta) if paths else "unknown"
        group = groups[(row["role"], model)]
        group["n"] += 1
        for key, value in (row.get("scores") or {}).items():
            if value and value[0].isdigit():
                group["scores"][key].append(int(value[0]))
        for cause in row["causes"]:
            group["causes"][cause] += 1
        if "no problem met" in row["report"].lower():
            group["noprob"] += 1

    def mean(values: list[int]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    print("role model n Task Brief Ease noprob top-causes")
    for key, group in sorted(groups.items(), key=lambda item: -item[1]["n"]):
        if group["n"] < MIN_N:
            continue
        s = group["scores"]
        print(
            key, group["n"], mean(s["Task"]), mean(s["Brief"]), mean(s["Ease"]), group["noprob"],
            dict(group["causes"].most_common(3)),
        )

    by_model = collections.defaultdict(lambda: collections.defaultdict(list))
    for (_, model), group in groups.items():
        for key, values in group["scores"].items():
            by_model[model][key] += values
    for model, scores in by_model.items():
        print(model, {key: (len(values), mean(values)) for key, values in scores.items()})


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)

# Ledger queries

Run with `uv run python`. Set `LEDGER` to the ledger path first. A report sent back is written again, so the ledger holds more rows than agents: every query keeps the last row per `agent_id` (the block below does it).

```python
import json, os, re, collections
latest = {}
for line in open(os.environ["LEDGER"]):
    row = json.loads(line)
    latest[row.get("agent_id") or id(row)] = row
rows = list(latest.values())
live = [r for r in rows if not r.get("imported")]

by = collections.defaultdict(collections.Counter)
for r in live:
    for c in r["causes"]:
        by[r["role"]][c] += 1

verdicts = collections.defaultdict(collections.Counter)
for r in live:
    verdicts[r["role"]][r.get("verdict")] += 1

def brief(r):
    m = re.match(r"# Report: ([^,]+), (.+)", r["report"])
    return (m.group(1), m.group(2).strip()) if m else None

grades = {(role, unit.strip()): int(g) for r in live if r["role"] == "auditor"
          for g, role, unit in re.findall(r"^Grade: (\d)/5 for (\S+) (.+)$", r["report"], re.M)}

pairs = [(brief(r), grades[brief(r)], r.get("verdict")) for r in live if brief(r) in grades]

waste = collections.defaultdict(list)
for r in live:
    if r.get("tool_turns"):
        waste[r["role"]].append(r["tool_turns"])
for role, items in waste.items():
    calls = sum(t["calls"] for t in items)
    print(role, len(items), round(calls / max(1, sum(t["turns"] for t in items)), 2),
          round(sum(t["repeats"] for t in items) / len(items), 1), round(sum(t["small_reads"] for t in items) / max(1, calls), 2))

capped = [r for r in live if not r["accepted"]]
```

What each block computes, in order:

- `by`: causes per role.
- `verdicts`: verdicts per role.
- `brief`: (role, task text) of a row, from the title `# Report: <role>, <task>`.
- `grades`: audit grades, from the line `Grade: N/5 for <role> <unit>`, where `<unit>` is the exact task text of the author's title.
- `pairs`: (brief, audit grade, verdict) for each audited unit.
- `waste`: tool turns per role: calls per turn, repeats per agent, share of calls that are small reads; rows before the field have none.
- `capped`: send-backs that stopped at the cap; only rows not accepted carry `open_problems`.

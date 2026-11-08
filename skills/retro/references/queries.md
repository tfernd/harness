# Ledger queries

Run with `uv run python`. Set `LEDGER` to the ledger path first.

```python
import json, os, re, collections
rows = [json.loads(line) for line in open(os.environ["LEDGER"])]
live = [r for r in rows if not r.get("imported")]

# causes per role
by = collections.defaultdict(collections.Counter)
for r in live:
    for c in r["causes"]:
        by[r["role"]][c] += 1

# verdicts per role
verdicts = collections.defaultdict(collections.Counter)
for r in live:
    verdicts[r["role"]][r.get("verdict")] += 1

# brief of a row: (role, task text) from the title "# Report: <role>, <task>"
def brief(r):
    m = re.match(r"# Report: ([^,]+), (.+)", r["report"])
    return (m.group(1), m.group(2).strip()) if m else None

# audit grades: the line "Grade: N/5 for <role> <unit>", <unit> = the exact task text of the author's title
grades = {(role, unit.strip()): int(g) for r in live if r["role"] == "auditor"
          for g, role, unit in re.findall(r"^Grade: (\d)/5 for (\S+) (.+)$", r["report"], re.M)}

# (brief, audit grade, verdict) for each audited unit
pairs = [(brief(r), grades[brief(r)], r.get("verdict")) for r in live if brief(r) in grades]

# tool turns per role: calls per turn, repeats per agent, share of calls that are small reads; rows before the field have none
waste = collections.defaultdict(list)
for r in live:
    if r.get("tool_turns"):
        waste[r["role"]].append(r["tool_turns"])
for role, items in waste.items():
    calls = sum(t["calls"] for t in items)
    print(role, len(items), round(calls / max(1, sum(t["turns"] for t in items)), 2),
          round(sum(t["repeats"] for t in items) / len(items), 1), round(sum(t["small_reads"] for t in items) / max(1, calls), 2))

# send-backs that stopped at the cap: only rows not accepted carry open_problems
capped = [r for r in live if not r["accepted"]]
```

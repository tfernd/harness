# Ledger queries

Run with `python3 -I`. Set `LEDGER` to the ledger path first.

```python
import json, os, re, collections
rows = [json.loads(line) for line in open(os.environ["LEDGER"])]
live = [r for r in rows if not r.get("imported")]

# causes per role
by = collections.defaultdict(collections.Counter)
for r in live:
    for c in r["causes"]:
        by[r["role"]][c] += 1

# self Task score per role
def task(r):
    v = (r["scores"] or {}).get("Task")
    return int(v[0]) if v and v[0].isdigit() else None

# brief of a row: (role, task text) from the title "# Report: <role>, <task>"
def brief(r):
    m = re.match(r"# Report: ([^,]+), (.+)", r["report"])
    return (m.group(1), m.group(2).strip()) if m else None

# audit grades: the line "Grade: N/5 for <role> <unit>", <unit> = the exact task text of the author's title
grades = {(role, unit.strip()): int(g) for r in live if r["role"] == "auditor"
          for g, role, unit in re.findall(r"^Grade: (\d)/5 for (\S+) (.+)$", r["report"], re.M)}

# (brief, audit grade, self Task) for each audited unit
pairs = [(brief(r), grades[brief(r)], task(r)) for r in live if brief(r) in grades]

# send-backs that stopped at the cap: only rows not accepted carry open_problems
capped = [r for r in live if not r["accepted"]]
```

# Brief checks

The sender's checks before a brief goes out. They are not text of the brief. Checks for a page or a mock brief:
`harness:workflows` (its explore reference).

- Every fact comes from a file read or a report, never memory. A name, count or path is checked by `rg`; a line is
  given as its text; a number carries its command.
- Every "or" in the job is decided, or asked of the owner.
- Every command the brief names exists and was run just before it goes out. A judge that already fails says so; the
  agent then reports a failure it did not cause as a problem with cause `other agent`.
- A judge that runs tests says how many should run: a run of zero tests exits 0.
- In a shared tree the judge is scoped to the brief's files; a repo-wide one fails on other agents' live files.
- The brief names every file the job writes, tests and docs included.
- A change to a public name or path lists every hit of the old one, found by `rg`, hidden folders included.
- The brief says what the agent cannot do (permissions, read-only, no network), so it reports `blocked` with the
  reason instead of going quiet.
- Re-read the whole brief: no sentence contradicts another, and none says how to build what the Goal and the Judge
  already settle.

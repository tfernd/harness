# Project review rules

The project's `AGENTS.md` may hold a "Review rules" section (template: `templates/AGENTS.md`). The reviewer reads it before the order of `harness:review` and follows it over the defaults.

| Entry | Effect |
|---|---|
| Severity A here | Adds to what counts as A; nothing in it lowers the A of `harness:review` |
| Skip | Paths and classes of finding that CI already enforces: not reported |
| Always check | Items checked on every review, reported even if clean |
| Accepted issues | Known issues, security ones included: not reported |

No section: the defaults apply. Say in the report that none was found.

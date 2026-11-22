---
name: introspect
description: Find where the harness plugin itself got in the way in this project (hook refusals, report send-backs, stop-gate blocks, plugin feedback agents wrote), judge each as a right rule, an agent's fault or a plugin bug, and only on the owner's ask report or fix it in the plugin's repository. Load when a hook refusal or send-back repeats, or the owner asks how the plugin is doing.
---

# Introspect

Two modes. Diagnose reads and changes nothing. Act runs only when the owner asks for it, never unasked.

## Diagnose

1. Run the script from the installed plugin. This skill's base directory is `<plugin>/skills/introspect`, so the launcher is two folders up:
   `<base directory>/../../bin/harness-introspect [--days N] [--project-dir <folder>]` (default 7 days). It reads the
   project from the current folder, so run it in the project folder, or pass `--project-dir`. It reads
   `~/.claude/projects/<slug>/` (main and `subagents/`), `~/.local/state/harness/<project>/reports/` and, when present,
   `~/.local/state/harness/<project>/refusals.jsonl` (the guard's own log of its refusals, local only), prints capped
   aggregates (refusals grouped by rule id, each with up to 3 samples that carry a short transcript id and agent id,
   plus the source it used; send-backs per agent, stop-gate blocks, friction, plugin feedback from reports, plugin
   version loaded against installed) and prints "nothing found" when there is no data. A version it cannot find reads
   "unknown". A refusal group is a rule id (`(rule: <id>)` in the message); an old-format refusal has no id and shows a
   plain search pattern for `rg` instead. The output holds the project's paths, commands, file and module names: it is
   for the owner only and is never pasted into an issue (Act, Privacy).
2. For the top items (most refusals, most send-backs, any friction line), read the plugin's own code in the same
   install folder: the rule's message in `hooks/guard.py`, `hooks/commit_gate.py`, `hooks/report_gate.py`, `hooks/turn.py`
   (`rg -n 'rule: <id>' <plugin>/hooks`, or the search pattern for an old-format refusal), and the skill that states the
   rule. Read the version the session loaded when it differs from the installed one: the folder is
   `~/.claude/plugins/cache/harness/harness/<sha>/`, and the script's plugin version section names the loaded sha. A
   refusal that the newer installed version already fixed is "already fixed: restart Claude Code", not a new bug. The full
   call and message of a sample are found by the transcript id and agent id printed with it (`~/.claude/projects/<slug>/`).
3. Sort each item into one class, with its quoted evidence marked READ, DERIVED or PROBED (`harness:evidence`):

| Class | It is when |
|---|---|
| The rule is right | the refused call did what the rule's text forbids, and the message named the fix |
| The agent's fault | the text was in front of the agent (skill, brief, message) and it was not followed |
| A plugin bug | a call inside the rule's own contract was refused, a message was wrong or silent about the fix, a rule contradicts a skill, or a loaded version is older than the installed one and the bug is fixed there |

Friction (3 or more refusals of one rule in a transcript, 3 or more near-identical retries, or an agent sent back 4 or
more times for the same missing sections) means the message did not tell the agent what to change, or, for the send-back,
that the agent never saw the report form or could not follow it: read the message before blaming the agent.

Report the sorted list to the owner, plugin bugs first, and stop. Offer Act; do not start it.

## Act (only when the owner asks)

The plugin's repository is the one its own README install line and `AGENTS.md` name: `tfernd/harness` on GitHub.

### Privacy, a hard rule

The repository is public. An issue, a pull request, a commit or a test case carries only the generic rule and a
made-up minimal example. Never a path, a command, a name, a host, a project or a domain from the project at hand: invent the example (`echo a > b.txt`), do not trim the real one.

Check every draft before the owner sees it:

1. Search it for the project's folder name, its absolute path, the home folder name, and the names of its code modules
   and its plan or config files.
2. Run `grep -n -i -F -f "${HARNESS_PRIVATE_WORDS:-$HOME/.config/harness/private-words}" <draft>` when that file exists.
3. When neither `$HARNESS_PRIVATE_WORDS` nor `~/.config/harness/private-words` exists, say so and ask the owner to read
   the draft with private words in mind; do not call it checked.

### Report

1. Draft the issue into `/tmp/harness/<project>/` (title, the generic rule, a made-up minimal reproduction, what
   the rule should do instead). Run the privacy check.
2. Show the draft to the owner. Post it only on the owner's yes: `gh issue create --repo tfernd/harness --title <title> --body-file <draft>`.

### Fix

1. Confirm a push right: `gh repo view tfernd/harness --json viewerPermission`. With none, stop at the report.
2. Clone into a new folder: `gh repo clone tfernd/harness /tmp/harness/<project>/introspect-<topic>/harness`.
3. Brief a `harness:worker` there with the generic rule, the made-up example and the judge `make check`; the
   Privacy rule binds the brief, the diff and every case.
4. Run `make check` in the clone and read the diff against the Privacy rule. Push the branch only on the owner's yes, given after the owner has read that diff; open the pull request (`harness:git`) only on a yes too.

## What no tool checks

Whether a sample is private after you made it generic, and whether a refusal was right: both are read, never trusted from a green run.

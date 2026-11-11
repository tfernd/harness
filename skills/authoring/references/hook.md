# Writing a hook

A hook runs on every matching call, for every agent. A wrong one slows or blocks all of them, so it is small, fast and
fails open.

## Events and what each can do

| Event | Can do |
|---|---|
| `PreToolUse` | Refuse the call (exit 2, message on stderr), ask the owner (`permissionDecision: ask`), or let it run with a note (`additionalContext`) |
| `PostToolUse` | Add context after the call; the call has already run |
| `UserPromptSubmit` | Add context before the model sees the prompt, or reset per-turn state |
| `Stop`, `SubagentStop` | Hold the stop: print `{"decision": "block", "reason": ...}`; the agent must act, then stop again |
| `SessionStart`, `SubagentStart` | Add context at the start |

The hooks of a plugin sit in `hooks/hooks.json`: one entry per command, each with a `matcher` (a tool name or
`A|B|C`; no matcher means every call) and a `timeout`. Read the event as JSON on stdin; use the fields you need.

## Rules

- **Stdlib only,** one script, run the way the project runs scripts. No network, no dependency.
- **Fail open.** A bug in a hook lets the call run: wrap `main()` in a catch that exits 1 (a non-blocking error, never 2).
  A refusal comes only from a rule that judged the input.
- **Budget.** A hook runs under a timeout of 10 seconds on every call. No work at hook time that grows with a
  project's history: no scan of a whole transcript or tree; keep a small state file and read that.
- **State:** per-machine data lives in the plugin's data folder (`$CLAUDE_PLUGIN_DATA`), which survives updates; project
  state lives in `~/.local/state/harness/<project>/` (`get_state_folder` in `hooks/common.py`). Never in the plugin's
  own folder or tracked files. A test fixture that runs a hook which writes project state lives outside the repo tree: the
  hook walks up from the cwd to the project and writes into the real state folder.
- **A refusal message names the rule and the change to make** ("blocked by <rule>: use X instead"), so the agent fixes
  the call at once. The same command in other words must not slip through, nor a harmless one be caught.
- **Soft against hard.** A hard rule (refuse) is for what is dangerous or wrong whatever the intent: a delete, a
  rewrite of history. A soft rule (a note, the call runs) is for a habit that costs time; the note says what to do next
  time. Start soft; harden a rule only after real data shows it never fires on a good call.
- **Config only overrides.** A rule works with no config; the owner's file turns it off or tunes it.
- **Judge the thing, not text that mentions it:** parse a command as a shell does; a quoted string or heredoc body is
  not a command.
- **Do not hold a stop forever.** A Stop hold has a cap on blocks, after which it lets go with one warning.

## What counts as built

A rule is built when it has all four:

1. **Cases:** inputs that must refuse, inputs that must pass (the near misses most of all), run by the project's case runner.
2. **A deliberate-bug control** that the cases catch (`harness:testing`): plant the bug in a copy of the hook, run
   the cases, see the failing line. A rule that cannot fail is not a rule.
3. **A replay on real data:** run the rule over real past commands or transcripts and read every hit. Passing cases only
   show the code matches your assumption; a replay shows what agents really did, and finds false refusals. A replay
   where fewer than one fire in ten is true is a reason to narrow the rule before the live run.
4. **A live run:** the plugin loaded in a real session (`claude --plugin-dir .` for a plugin), the rule fired once and
   its message read as an agent would read it.

A judge that imports a hook by path loads the hook's sibling modules first.

## What no tool checks

Whether a message is clear to an agent that has only that text, and whether a rule is worth the friction it causes.
Give the message to a fresh agent with nothing else.

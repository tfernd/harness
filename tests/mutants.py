#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""The control of the hook cases: each mutant breaks one rule in a copy of the hooks, and some case must then fail.

Why: a case that cannot fail proves nothing. A mutant that stays green is a rule no case guards. A mutant whose old text
is gone from its hook is an error, so the list cannot rot. A row prints per mutant as it finishes; the exit code is 1 when
any mutant survives. Copies go under `scratch/hook-mutants`. Stdlib only.

uv run python tests/mutants.py [--only SUBSTRING] [--jobs N] [--check]

`--check` runs nothing and only finds the mutants whose text is gone, in a second, so the pre-push hook and CI can run it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
HOOKS = HARNESS / "hooks"
RUN_CASES = HARNESS / "tests" / "run_cases.py"
WORK = HARNESS / "scratch" / "hook-mutants"
TIMEOUT = 170
# Each case starts `uv` and a hook, so jobs times threads is what the machine carries: 6 on 24 cores. Six jobs of eight froze one.
CASE_THREADS = 2
DEFAULT_JOBS = max(1, (os.cpu_count() or 8) // 8)
LOW_PRIORITY = 10
# Name, file, the text to break, what it becomes.
MUTANTS = (
    # What the sub-agents' feedback asked for.
    ("context-no-tools-text", "context.py", "lines = [TOOLS_TEXT]", "lines = []"),
    ("context-zsh-always", "context.py", 'if os.path.basename(os.environ.get("SHELL") or "") == "zsh":', "if True:"),
    ("context-no-setup-for-session", "context.py", "get_setup_text(config), get_retro_line(root))", "get_retro_line(root))"),
    ("context-no-setup-for-agent", "context.py", "get_setup_text(config), get_lessons(root, agent_type))", "get_lessons(root, agent_type))"),
    ("context-scratch-unnamed", "context.py", 'if guard.get("scratch"):', "if False:"),
    ("context-tmp-always", "context.py", 'if guard.get("no_tmp"):', "if True:"),
    ("budget-note-never", "budget.py", "if num_turns != limit - left:", "if True:"),
    ("budget-note-every-turn", "budget.py", "if num_turns != limit - left:", "if num_turns > limit - left:"),
    ("budget-note-no-floor", "budget.py", "left = max(MIN_TURNS_LEFT, limit // 5)", "left = limit // 5"),
    ("budget-note-not-context", "budget.py", '"additionalContext": warning', '"note": warning'),
    # The independent review's nine.
    ("herestring-word-kept-as-argument", "shell.py", 'if operator.startswith("<<<"):\n            self.target = "herestring"', 'if operator.startswith("<<<"):\n            self.target = ""'),
    ("heredoc-bodies-read-as-commands", "shell.py", 'if operator == "\\n" and self.heredocs:\n            self.skip_heredocs()', 'if operator == "\\n" and self.heredocs:\n            self.heredocs = []'),
    ("python-c-read-as-shell", "guard.py", 'SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}', 'SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "python3"}'),
    ("lessons-none-ignored", "turn.py", "if not section or LESSONS_NONE.search(section):", "if not section:"),
    ("deferred-count-not-kept", "turn.py", "if calls >= min_calls and not is_deferred:", "if calls >= min_calls:"),
    ("count-never-emptied", "turn.py", 'if calls >= min_calls and not is_deferred:\n        calls_path.write_text("")', "if False:\n        pass"),
    ("out-of-order-not-checked", "report_gate.py", 'problems.append(f"out of order: {heading}")', "pass"),
    ("git-reset-any", "guard.py", 'return subcommand == "reset" and "--hard" in arguments', 'return subcommand == "reset"'),
    ("blocks-not-reset-at-pass", "turn.py", 'blocks_path.write_text("0")\n    if problems:', "if problems:"),
    ("free-prefixes-ignored", "guard.py", "and not script.startswith(POLICY.free_prefixes)", ""),
    # The shell reader.
    ("arithmetic-read-as-commands", "shell.py", 'if text.startswith("$((", start):', 'if False:'),
    ("arithmetic-substitution-not-read", "shell.py", "self.read_expansions(start + 3, end - 2)", "pass"),
    ("nested-subshells-read-as-arithmetic", "shell.py", 'return index + 2 if text[index + 1 : index + 2] == ")" else -1', "return index + 2"),
    ("arithmetic-command-read-as-commands", "shell.py", 'text.startswith("((", self.index) and self.is_arithmetic_start()', 'False and self.is_arithmetic_start()'),
    ("test-read-as-commands", "shell.py", 'elif text.startswith("[[", self.index) and self.is_command_start()', 'elif False and self.is_command_start()'),
    ("test-substitution-not-read", "shell.py", 'elif character in "$`":\n                self.read_dollar()\n            else:\n                self.characters.append(character)', 'elif False:\n                self.read_dollar()\n            else:\n                self.characters.append(character)'),
    ("parameter-read-by-characters", "shell.py", 'elif following == "{":\n            self.index = self.read_parameter(self.index, False)', 'elif False:\n            pass'),
    ("parameter-substitution-not-read", "shell.py", 'elif text.startswith("$(", index) or text[index] == "`":\n                index = self.read_substitution(index)\n            else:\n                index += 1\n        self.characters.append("$")', 'else:\n                index += 1\n        self.characters.append("$")'),
    ("process-substitution-not-read", "shell.py", 'elif text.startswith(("<(", ">("), self.index):', 'elif False:'),
    ("redirect-operator-swallows-dash", "shell.py", 'REDIRECT_OPERATOR = re.compile(r"<<<|<<-|<<|<>|<&|<|&>>|&>|>>|>&|>\\||>")', 'REDIRECT_OPERATOR = re.compile(r"[<>&|-]+")'),
    ("redirect-target-survives-the-segment", "shell.py", 'self.end_word()\n        self.target = ""\n', "self.end_word()\n"),
    ("unquoted-heredoc-body-not-read", "shell.py", "if not heredoc.is_quoted:", "if False:"),
    ("quoted-heredoc-body-read", "shell.py", "if not heredoc.is_quoted:", "if True:"),
    ("closing-paren-ignores-case", "shell.py", 'self.depth == 0 and self.case_depth == 0:', "self.depth == 0:"),
    ("one-pipe-marks-the-whole-command", "shell.py", 'elif has_command or operator != "\\n":', "elif False:"),
    ("pipeline-first-command-not-grouped", "shell.py", "self.segments[-1] = self.segments[-1]._replace(in_group=True)", "pass"),
    ("background-not-grouped", "shell.py", 'if operator == "&":', "if False:"),
    # The guard.
    ("push-cluster-not-read", "guard.py", "if is_cluster(argument) and PUSH_DENIED_LETTERS & set(argument[1:]):", "if False:"),
    ("shell-cluster-not-read", "guard.py", 'has_string_option = has_string_option or (is_cluster(argument) and "c" in argument)', 'has_string_option = has_string_option or argument == "-c"'),
    ("shell-value-option-not-skipped", "guard.py", "if argument in SHELL_VALUE_OPTIONS:", "if False:"),
    ("find-exec-not-read", "guard.py", 'if name == "find":\n        return get_find_runs(command.arguments)', 'if False:\n        pass'),
    ("find-execdir-not-read", "guard.py", 'FIND_RUNNERS = {"-exec", "-execdir", "-ok", "-okdir"}', 'FIND_RUNNERS = {"-exec", "-ok", "-okdir"}'),
    ("find-ok-not-read", "guard.py", 'FIND_RUNNERS = {"-exec", "-execdir", "-ok", "-okdir"}', 'FIND_RUNNERS = {"-exec", "-execdir", "-okdir"}'),
    ("sudo-options-not-skipped", "guard.py", 'index = skip_options(words, index + 1, OPTION_PREFIXES[word])', 'index = index + 1'),
    ("sudo-values-not-skipped", "guard.py", '"sudo": {"-u", "-g",', '"sudo": {"-g",'),
    ("git-value-options-not-skipped", "guard.py", 'GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree",', 'GIT_VALUE_OPTIONS = {"-C", "-c",'),
    ("eval-not-read", "guard.py", 'if name == "eval":\n        return get_segments(" ".join(arguments))', 'if False:\n        pass'),
    ("python-m-pip-allowed", "guard.py", 'return name.startswith("python") and is_module_pip(arguments)', "return False"),
    ("uv-run-pip-allowed", "guard.py", 'return arguments[index:index + 1] in (["pip"], ["pip3"]) or is_module_pip(arguments[index + 1 :])', "return False"),
    ("mv-source-not-written", "guard.py", 'if name != "mv":\n        return []', "return []"),
    ("mv-source-counts-as-temporary", "guard.py", 'any(is_temporary(path) for path in written)', 'any(is_temporary(path) for path in [*written, *moved])'),
    ("cp-t-not-read", "guard.py", 'targets = get_option_values(arguments, "t", "--target-directory") if name in TARGET_MOVERS else []', "targets = []"),
    ("paths-compared-unresolved", "guard.py", "return os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))", "return os.path.normpath(os.path.join(cwd, os.path.expanduser(path)))"),
    ("scratch-not-normalized", "common.py", "return os.path.realpath(root / scratch) if scratch else \"\"", 'return os.path.join(str(root), scratch) if scratch else ""'),
    ("declare-values-count-as-globs", "guard.py", "not (is_declarer and ASSIGNMENT.match(word.text))", "True"),
    ("matched-glob-refused", "guard.py", 'return next(glob.iglob(resolve_path(text, directory or ""), recursive=True), None) is None', "return True"),
    ("unmatched-glob-allowed", "guard.py", 'return next(glob.iglob(resolve_path(text, directory or ""), recursive=True), None) is None', "return False"),
    ("glob-not-recursive", "guard.py", 'directory or ""), recursive=True)', 'directory or ""), recursive=False)'),
    ("glob-ignores-the-cd", "guard.py", "has_failing_glob(command, directory, globs[1])", "has_failing_glob(command, POLICY.root, globs[1])"),
    ("option-glob-judged-as-path", "guard.py", 'if text.startswith("-"):\n        return True', "if False:\n        return True"),
    ("expansion-glob-judged-as-path", "guard.py", "if may_have_written or any(character in text for character in UNEXPANDED) or (", "if may_have_written or ("),
    ("unknown-folder-glob-judged", "guard.py", " or (directory is None and not is_absolute(text)):", ":"),
    ("absolute-glob-not-judged", "guard.py", "(directory is None and not is_absolute(text))", "directory is None"),
    ("glob-pattern-option-not-refused", "guard.py", "is_pattern = index > 0 and command.arguments[index - 1].text in pattern_options", "is_pattern = False"),
    ("glob-pattern-options-of-any-command", "guard.py", "pattern_options = GLOB_PATTERN_OPTIONS.get(name, set())", 'pattern_options = {"-name"}'),
    # The project.
    ("project-follows-the-cwd", "common.py", 'Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()', "Path(cwd).resolve()"),
    ("project-ignores-the-cwd", "common.py", 'Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()', 'Path(os.environ.get("CLAUDE_PROJECT_DIR") or "/").resolve()'),
    # The roles.
    ("every-role-judged", "common.py", '    return ""\n\n\ndef get_unfenced_lines', '    return "full"\n\n\ndef get_unfenced_lines'),
    ("report-short-ignored", "common.py", 'if role in SHORT_ROLES or role in settings.get("short", ()):', "if role in SHORT_ROLES:"),
    ("report-full-ignored", "common.py", 'if role in FULL_ROLES or role in settings.get("full", ()):', "if role in FULL_ROLES:"),
    ("prefix-not-removed", "common.py", "role = agent_type.removeprefix(PLUGIN_PREFIX)", "role = agent_type"),
    ("unterminated-fence-hides", "common.py", 'return [line for index, line in enumerate(lines) if index not in fenced]', 'return [line for index, line in enumerate(lines) if index not in fenced and (opened < 0 or index < opened)]'),
    # The report gate.
    ("user-lines-count", "report_gate.py", 'if entry.get("type") == "assistant":\n                    blocks.append(block)', "if True:\n                    blocks.append(block)"),
    ("any-heading-is-the-report", "report_gate.py", "if ANSWER_HEADING.search(last):", 'if "## " in last:'),
    ("first-report-wins", "report_gate.py", "if isinstance(text, str) and ANSWER_HEADING.search(text):\n            report = text", "if isinstance(text, str) and ANSWER_HEADING.search(text) and not report:\n            report = text"),
    ("handback-not-read", "report_gate.py", 'is_handback = block.get("type") == "tool_use" and block.get("name") == HANDBACK_TOOL', "is_handback = False"),
    ("changed-files-not-checked", "report_gate.py", "if not is_exempt and not is_named(path, report, folders):", "if False:"),
    ("scratch-not-exempt", "report_gate.py", "is_exempt = scratch and (path == scratch or path.startswith(scratch + os.sep))", "is_exempt = False"),
    ("failed-edit-counts", "report_gate.py", 'and block.get("id") not in failed:', ":"),
    ("notebook-edit-ignored", "common.py", 'EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}', 'EDIT_TOOLS = {"Edit", "Write"}'),
    ("named-by-substring", "report_gate.py", 'return re.search(rf"(?<![\\w./-])(?:\\./)?(?:{pattern})(?![\\w/-]|\\.\\w)", report) is not None', "return any(spelling in report for spelling in spellings)"),
    ("exit-claim-not-checked", "report_gate.py", "if EXIT_CODE.search(report) and not has_bash:", "if False:"),
    ("read-claim-not-checked", "report_gate.py", "problems = check_read_claims(report, root)", "problems = []"),
    ("read-range-checks-its-start", "report_gate.py", "line = int(last or first)", "line = int(first)"),
    ("read-missing-file-allowed", "report_gate.py", 'problems.append(f"READ names a file that does not exist: {path}")', "pass"),
    ("no-feedback-words-filed", "report_gate.py", 'NO_FEEDBACK = re.compile(r"(none|none needed|no feedback|n/?a)[ .]*", re.I)', 'NO_FEEDBACK = re.compile(r"(none)[ .]*", re.I)'),
    ("inbox-line-without-session", "report_gate.py", 'f"- id={item_id} session={session} agent={role} {text}\\n"', 'f"- id={item_id} agent={role} {text}\\n"'),
    ("known-item-across-sessions", "report_gate.py", 'if f"id={item_id} session={session} " not in known:', 'if f"id={item_id} " not in known:'),
    # The turn.
    ("feedback-of-every-session", "turn.py", "if owner == session]", "]"),
    ("released-ids-still-hold", "turn.py", "and item_id not in released]", "]"),
    ("released-ids-not-saved", "turn.py", 'released_path.write_text(" ".join(sorted(released | set(open_ids))))', "pass"),
    ("worktree-counts-as-a-rule", "turn.py", "and not (is_claude and name == WORKTREES[1])", ""),
    ("any-status-after-the-id-finishes", "turn.py", "for tool_id, status in found if status in FINISHED_STATUSES", "for tool_id, status in found"),
    ("reset-empties-a-deferred-count", "turn.py", 'if not is_app_prompt and not get_state_path(event.get("session_id") or "unknown", "deferred").exists():', "if not is_app_prompt:"),
    ("deferred-mark-not-written", "turn.py", 'deferred_path.write_text("1")', "pass"),
    ("deferred-mark-not-cleared", "turn.py", "if not is_deferred and deferred_path.exists():\n        deferred_path.unlink()", "if False:\n        pass"),
    # The delegate rule.
    ("delegate-judges-sub-agents", "delegate.py", 'if event.get("agent_id"):\n        return 0\n', ""),
    ("delegate-without-its-key", "delegate.py", 'if root is None or "delegate" not in config:', "if root is None:"),
    ("delegate-first-command-only", "delegate.py", "for segment in get_segments(command):", "for segment in get_segments(command)[:1]:"),
    ("delegate-prefix-by-text", "delegate.py", "return any(words[: len(prefix)] == prefix for prefix in prefixes)", 'return any(" ".join(words).startswith(" ".join(prefix)) for prefix in prefixes)'),
    ("delegate-redirect-allowed", "delegate.py", "if any(target != NULL_DEVICE for target in segment.redirects):", "if False:"),
    ("delegate-null-refused", "delegate.py", "if any(target != NULL_DEVICE for target in segment.redirects):", "if segment.redirects:"),
    ("delegate-bash-allow-ignored", "delegate.py", 'allowed = [*DEFAULT_BASH_ALLOW, *settings.get("bash_allow", ())]', "allowed = [*DEFAULT_BASH_ALLOW]"),
    ("delegate-bash-allow-replaces", "delegate.py", 'allowed = [*DEFAULT_BASH_ALLOW, *settings.get("bash_allow", ())]', 'allowed = [*settings.get("bash_allow", DEFAULT_BASH_ALLOW)]'),
    ("delegate-head-missing", "delegate.py", '    "head",\n', ""),
    ("delegate-wc-missing", "delegate.py", '    "wc",\n', ""),
    ("delegate-bare-cat-refused", "delegate.py", 'if words == ["cat"]:', "if False:"),
    ("delegate-any-cat-allowed", "delegate.py", 'if words == ["cat"]:', 'if words[:1] == ["cat"]:'),
    ("delegate-handled-refused", "delegate.py", "if relative == HANDLED:", "if False:"),
    ("delegate-outside-allowed", "delegate.py", "if root not in resolved.parents:\n        return False\n", "if root not in resolved.parents:\n        return True\n"),
    ("delegate-write-allow-ignored", "delegate.py", 'return any(fnmatch.fnmatch(relative, pattern) for pattern in settings.get("write_allow", ()))', "return False"),
    # The budget rule.
    ("budget-judges-the-main-session", "budget.py", 'if not event.get("agent_id") or event.get("tool_name") == HANDBACK_TOOL:', 'if event.get("tool_name") == HANDBACK_TOOL:'),
    ("budget-never-refuses", "budget.py", "if num_turns <= limit:", "if True:"),
    ("budget-always-refuses", "budget.py", "if num_turns <= limit:", "if False:"),
    ("budget-current-call-free", "budget.py", "len(turns) + (not is_written)", "len(turns)"),
    ("budget-no-id-counts-one-more", "budget.py", "is_written = not call_id or any(", "is_written = any("),
    ("budget-one-early", "budget.py", "if num_turns <= limit:", "if num_turns < limit:"),
    ("budget-counts-calls", "budget.py", "num_turns = len(turns) + (not is_written)", "num_turns = sum(map(len, turns)) + (not is_written)"),
    ("budget-line-ignored", "budget.py", "limit = get_turn_limit(get_brief(first))", "limit = None"),
    ("budget-default-wins", "budget.py", "    if limit is None:\n        limit = get_default(config, role)", "    limit = get_default(config, role)"),
    ("budget-defaults-ignore-config", "budget.py", 'config.get("budget", DEFAULT_BUDGET).get(role)', "DEFAULT_BUDGET.get(role)"),
    ("budget-unknown-role-gets-a-budget", "budget.py", 'config.get("budget", DEFAULT_BUDGET).get(role)', 'config.get("budget", DEFAULT_BUDGET).get(role, 1)'),
    ("budget-fence-read", "budget.py", "for line in get_unfenced_lines(brief):", "for line in brief.splitlines():"),
    ("budget-turns-word-refused", "budget.py", "(?:turns?\\b|(?=\\W*$))", "(?=\\W*$)"),
    ("budget-any-number-counts", "budget.py", "|(?=\\W*$))", "|)"),
    ("budget-line-must-fill-the-line", "budget.py", "BUDGET_LINE.search(", "BUDGET_LINE.fullmatch("),
    ("budget-quote-counts", "budget.py", 'QUOTED.sub("", line)', "line"),
    ("budget-prose-counts", "budget.py", '(?:^|[.;]\\s+)[\\s\\-*#]*budget', "budget"),
    ("budget-refuses-the-handback", "budget.py", ' or event.get("tool_name") == HANDBACK_TOOL', ""),
    ("budget-list-brief-ignored", "budget.py", "if isinstance(content, list):", "if False:"),
    ("budget-message-silent", "budget.py", "Send your report now as a partial report: done, not done, what is on disk.", "Stop."),
    ("budget-prefix-kept", "budget.py", 'event.get("agent_type") or "").removeprefix(PLUGIN_PREFIX)', 'event.get("agent_type") or "")'),
    ("budget-bug-blocks", "budget.py", "sys.exit(1)", "sys.exit(2)"),
    ("ledger-duration-dropped", "report_gate.py", '"duration_s": duration,', '"duration_s": None,'),
    ("ledger-duration-from-first-only", "budget.py", "round(last - first, 1)", "0.0"),
    # The brief rule.
    ("brief-judges-sub-agents", "brief_lint.py", 'if event.get("agent_id"):\n        return 0\n', ""),
    ("brief-without-its-key", "brief_lint.py", 'if root is None or "brief" not in config:', "if root is None:"),
    ("brief-judges-every-type", "brief_lint.py", "if role not in ROLES:\n        return 0\n", ""),
    ("brief-prefix-not-removed", "brief_lint.py", '.removeprefix(PLUGIN_PREFIX)', ""),
    ("brief-required-ignored", "brief_lint.py", '(config["brief"] or {}).get("required", DEFAULT_REQUIRED)', "DEFAULT_REQUIRED"),
    ("brief-worker-needs-no-judge", "brief_lint.py", '"worker": ["Goal:", "Write set:", "Judge:"]', '"worker": ["Goal:", "Write set:"]'),
    ("brief-label-anywhere", "brief_lint.py", "any(line.startswith(label) for line in lines)", "any(label in line for line in lines)"),
    ("brief-bold-label-refused", "brief_lint.py", 'LINE_MARKS = " \\t-*#"', 'LINE_MARKS = " \\t"'),
    # The handback and the glob rule's exceptions.
    ("gate-sends-back-an-ended-agent", "report_gate.py", 'bool(blocks) and blocks[-1].get("name") == HANDBACK_TOOL or ', ""),
    ("gate-no-report-sent-back", "report_gate.py", ' or (os.path.isfile(path) and not report)', ""),
    ("gate-every-agent-has-ended", "report_gate.py", "if has_ended or tries >= MAX_SEND_BACKS:", "if True:"),
    ("glob-judged-in-any-shell", "guard.py", 'os.path.basename(os.environ.get("SHELL") or "") == "zsh"', "True"),
    ("glob-judged-in-bash-c", "guard.py", 'judges_globs and not (name in SHELLS and name != "zsh")', "judges_globs"),
    ("glob-never-judged-in-zsh-c", "guard.py", 'name in SHELLS and name != "zsh"', "name in SHELLS"),
    ("glob-judged-after-a-write", "guard.py", "if may_have_written or any(", "if any("),
    ("glob-skipped-after-a-read", "guard.py", "may_have_written or name not in READ_ONLY_COMMANDS", "True"),
    ("glob-redirect-is-no-write", "guard.py", " or bool(get_written_words(segment, command, directory))", ""),
    ("glob-rule-off", "guard.py", "globs[0] and has_failing_glob", "False and has_failing_glob"),
    ("baseline-moved-by-the-app", "turn.py", "if not is_app_prompt and not get_state_path", "if not get_state_path"),
    ("baseline-never-moved", "turn.py", 'bool(APP_PROMPT.search(str(event.get("prompt") or "")[:APP_PROMPT_HEAD]))', "True"),
    ("brief-unreadable-budget-passes", "brief_lint.py", 'if has_unreadable_budget(tool_input.get("prompt") or ""):', "if False:"),
    ("brief-prose-refused", "brief_lint.py", "LABELLED_BUDGET.search(line)", '"budget" in line.lower()'),
    ("brief-any-budget-refused", "brief_lint.py", "and get_turn_limit(line) is None", ""),
    ("brief-fence-read", "brief_lint.py", "for line in get_unfenced_lines(prompt)]", "for line in prompt.splitlines()]"),
    ("brief-quote-read", "brief_lint.py", '[QUOTED.sub("", line) for', "[line for"),
    ("nudge-cd-semicolon-missed", "nudge.py", "(?:&&|;)", "&&"),
    ("import-tool-turns-lost", "import_reports.py", '"tool_turns": get_turn_stats(events),', '"tool_turns": None,'),
    # The tool-turn nudge.
    ("nudge-without-a-project", "nudge.py", "if root is None:\n        return 0\n", ""),
    ("nudge-run-short", "nudge.py", "RUN_LENGTH = 4", "RUN_LENGTH = 3"),
    ("nudge-run-never", "nudge.py", "if run and run % RUN_LENGTH == 0:", "if False:"),
    ("nudge-two-calls-count-as-one", "nudge.py", "is_small_turn = len(turn) == 1 and is_small_read(turn[0])", "is_small_turn = is_small_read(turn[0])"),
    ("nudge-repeat-never", "nudge.py", "if key in seen:", "if False:"),
    ("nudge-command-forgets-reads", "nudge.py", 'if call.get("name") in EDIT_TOOLS:', "if True:"),
    ("nudge-edit-keeps-reads", "nudge.py", "seen.clear()", "pass"),
    ("nudge-sed-i-reads", "nudge.py", "^sed\\s(.*\\s)?-i|", ""),
    ("nudge-batch-reads", "nudge.py", 'r";|&&|', 'r"'),
        ("nudge-long-transcript-read", "nudge.py", " or path.stat().st_size > MAX_BYTES", ""),
    ("nudge-no-cap", "nudge.py", "waste.nudges[:MAX_NUDGES]", "waste.nudges"),
    ("nudge-any-call-hears", "nudge.py", "dict(waste.nudges[:MAX_NUDGES]).get(call_id)", "next((text for _, text in waste.nudges[:MAX_NUDGES]), None)"),
    ("nudge-reads-the-session", "nudge.py", 'get_agent_path(event) if event.get("agent_id") else ', ""),
    ("nudge-silent", "nudge.py", "    if text:\n", "    if False:\n"),
    ("nudge-bug-blocks", "nudge.py", "sys.exit(1)", "sys.exit(2)"),
    ("ledger-tool-turns-lost", "report_gate.py", "get_turn_stats(read_events(path)) if path else None", "None"),
    # The context hook.
    ("context-session-silent", "context.py", "(SESSION_TEXT, TOOL_TURNS_TEXT,", '("", TOOL_TURNS_TEXT,'),
    ("context-forms-swapped", "context.py", 'FORM_TEXTS.get(form, "")', 'FORM_TEXTS.get("full" if form == "short" else "short", "") if form else ""'),
    ("context-tells-every-agent", "context.py", 'FORM_TEXTS.get(form, "")', 'FORM_TEXTS.get(form, FORM_TEXTS["full"])'),
    ("context-tool-turns-not-for-session", "context.py", "(SESSION_TEXT, TOOL_TURNS_TEXT,", "(SESSION_TEXT,"),
    ("context-tool-turns-not-for-agents", "context.py", 'FORM_TEXTS.get(form, ""), TOOL_TURNS_TEXT,', 'FORM_TEXTS.get(form, ""),'),
    ("context-without-a-project", "context.py", "if root is None:\n        return 0\n", ""),
    # The report gate's claim and auto-item rules.
    ("exit-claim-matches-any-code", "report_gate.py", "        if code not in seen\n", "        if False\n"),
    ("failed-call-counts-as-exit-zero", "report_gate.py", "            if call_id not in failed:\n                seen.add(0)", "            if True:\n                seen.add(0)"),
    ("read-quote-not-checked", "report_gate.py", "if not all(part in window for part in parts if part):", "if False:"),
    ("read-quote-searches-the-whole-file", "report_gate.py", "lines[first_line : line + QUOTE_WINDOW]", "lines"),
    ("auto-decide-not-filed", "report_gate.py", 'for heading in ("DECIDE", "OUTSIDE"):', 'for heading in ("OUTSIDE",):'),
    ("auto-outside-not-filed", "report_gate.py", 'for heading in ("DECIDE", "OUTSIDE"):', 'for heading in ("DECIDE",):'),
    ("auto-none-bullet-filed", "report_gate.py", 'for text in texts if text and not NO_FEEDBACK.fullmatch(text)]\n    for line in sections', 'for text in texts]\n    for line in sections'),
    ("auto-low-task-not-filed", "report_gate.py", "if score and int(score.group(1)) <= LOW_TASK:", "if False:"),
    ("auto-high-task-filed", "report_gate.py", "if score and int(score.group(1)) <= LOW_TASK:", "if score:"),
    # The turn's handled-line check.
    ("handled-file-missing-accepted", "turn.py", "if not path.is_file():", "if False:"),
    ("handled-file-unchanged-accepted", "turn.py", "if json.loads(rules_path.read_text()).get(str(path)) == state[str(path)]:", "if False:"),
    ("handled-file-not-a-rule-accepted", "turn.py", "if str(path) not in state:", "if False:"),
    ("handled-no-file-named-accepted", "turn.py", "if not name:\n        return", "if False:\n        return"),
    ("rejected-reason-length-ignored", "turn.py", "is_short = len(reason.split()) < MIN_REASON_WORDS", "is_short = False"),
    ("rejected-two-words-pass", "turn.py", "MIN_REASON_WORDS = 3", "MIN_REASON_WORDS = 2"),
    # The skill gate.
    ("skill-gate-always-allows", "skill_gate.py", "return 2 if missing else 0", "return 0"),
    ("skill-gate-scratch-not-exempt", "skill_gate.py", "if scratch and (absolute == scratch", "if False and (absolute == scratch"),
    ("skill-gate-bare-name-refused", "skill_gate.py", "return skill.removeprefix(PLUGIN_PREFIX)", "return skill"),
    ('skill-gate-reads-the-session-transcript', "skill_gate.py", 'if event.get("agent_id"):\n        return get_agent_path(event)', 'if False:\n        return get_agent_path(event)'),
    # The folders.
    ("feedback-in-the-dot-folder", "common.py", 'FEEDBACK_FOLDER = "harness-feedback"', 'FEEDBACK_FOLDER = ".harness"'),
)


def run_mutant(name: str, script: str, old: str, new: str, /) -> tuple[str, int, list[str]]:
    """Breaks a copy of the hooks and runs the cases on it; returns the name, the exit code and the failed cases."""

    folder = WORK / name
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree(HOOKS, folder, ignore=shutil.ignore_patterns("__pycache__"))
    path = folder / script
    path.write_text(path.read_text().replace(old, new))
    command = ["uv", "run", "python", str(RUN_CASES), "--hooks", str(folder), "--fail-fast", "--first", script, "--threads", str(CASE_THREADS)]
    run = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT)
    failed = [line[5:].split(":")[0] for line in run.stdout.splitlines() if line.startswith("FAIL")]
    shutil.rmtree(folder)

    return name, run.returncode, failed


def get_rotted_names() -> list[str]:
    """The mutants whose text to break is gone from their hook, which would prove nothing."""

    return [name for name, script, old, _ in MUTANTS if old not in (HOOKS / script).read_text()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default="", help="run the mutants whose name holds this text")
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help="mutants at once; each runs its cases on CASE_THREADS threads")
    parser.add_argument("--check", action="store_true", help="only find the mutants whose text is gone")
    arguments = parser.parse_args()
    rotted = get_rotted_names()
    if rotted or arguments.check:
        print(f"{len(MUTANTS)} mutants, {len(rotted)} with their text gone: {rotted}")
        return 1 if rotted else 0
    chosen = [mutant for mutant in MUTANTS if arguments.only in mutant[0]]
    survivors = 0
    os.nice(LOW_PRIORITY)
    with ThreadPoolExecutor(arguments.jobs) as pool:
        futures = [pool.submit(run_mutant, *mutant) for mutant in chosen]
        for future in as_completed(futures):
            name, code, failed = future.result()
            survivors += code == 0
            verdict = "SURVIVED" if code == 0 else f"killed by {len(failed)}"
            print(f"{verdict:16} {name}: {failed[:2]}", flush=True)
    print(f"{len(chosen)} mutants, {survivors} survived")

    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())

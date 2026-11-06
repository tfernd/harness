#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
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
import ast
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import NamedTuple

HARNESS = Path(__file__).resolve().parent.parent
HOOKS = HARNESS / "hooks"
RUN_CASES = HARNESS / "tests" / "run_cases.py"
WORK = HARNESS / "scratch" / "hook-mutants"
TIMEOUT = 170
# Each case starts `uv` and a hook, so jobs times threads is what the machine carries: 6 on 24 cores. Six jobs of eight froze one.
CASE_THREADS = 2
DEFAULT_JOBS = max(1, (os.cpu_count() or 8) // 8)
LOW_PRIORITY = 10
# Returned in place of an exit code when the cases on a mutant ran past TIMEOUT: the mutant is neither killed nor survived.
TIMED_OUT = -1
# Name, file, the text to break, what it becomes.
MUTANTS = (
    # A package change asks.
    ("packages-refused", "guard.py", "    if not lines:\n        decision", "    if False:\n        decision"),
    ("packages-pass-silently", "guard.py", '"permissionDecision": "ask"', '"permissionDecision": "allow"'),
    ("packages-old-key-dropped", "guard.py", 'guard.get("ask_packages") or guard.get("deny_packages")', 'guard.get("ask_packages")'),
    ("packages-new-key-dropped", "guard.py", 'guard.get("ask_packages") or guard.get("deny_packages")', 'guard.get("deny_packages")'),
    ("packages-other-rule-asks", "guard.py", 'for rule in hard if rule != ASK_RULE]', 'for rule in hard if rule not in (ASK_RULE, "delete")]'),
    # What the sub-agents' feedback asked for.
    ("context-no-tools-text", "context.py", "lines = [TOOLS_TEXT]", "lines = []"),
    ("context-zsh-always", "context.py", 'if os.path.basename(os.environ.get("SHELL") or "") == "zsh":', "if True:"),
    ("context-no-setup-for-session", "context.py", "get_setup_text(config), get_retro_line(root))", "get_retro_line(root))"),
    ("context-no-setup-for-agent", "context.py", "get_setup_text(config), get_lessons(root, agent_type), get_open_problems(root, agent_type))", "get_lessons(root, agent_type), get_open_problems(root, agent_type))"),
    ("context-scratch-unnamed", "context.py", 'if guard.get("scratch"):', "if False:"),
    ("context-tmp-always", "context.py", 'if guard.get("no_tmp"):', "if True:"),
    ("budget-note-never", "budget.py", "if num_turns != limit - left:", "if True:"),
    ("budget-note-every-turn", "budget.py", "if num_turns != limit - left:", "if num_turns > limit - left:"),
    ("budget-note-no-floor", "budget.py", "left = max(MIN_TURNS_LEFT, limit // 5)", "left = limit // 5"),
    ("budget-note-not-context", "budget.py", '"additionalContext": warning', '"note": warning'),
    # State files are never read half-written.
    ("torn-blocks-count-raises", "turn.py", "blocks = int(count) if count.isdecimal() and count.isascii() else 0", "blocks = int(count)"),
    ("torn-rules-raise", "turn.py", "    except (OSError, ValueError):\n        return None\n\n    return saved if", "    except OSError:\n        return None\n\n    return saved if"),
    ("torn-rules-not-object-raise", "turn.py", "return saved if isinstance(saved, dict) else None", "return saved"),
    ("torn-send-back-count-raises", "report_gate.py", "    except (OSError, ValueError):\n        return 0\n", "    except OSError:\n        return 0\n"),
    ("torn-kept-report-raises", "report_gate.py", "    except (ValueError, KeyError, TypeError):\n        return None", "    except (KeyError, TypeError):\n        return None"),
    ("torn-temporary-file-left", "common.py", "os.replace(temporary, path)\n    finally:\n        temporary.unlink(missing_ok=True)", "path.write_text(text)\n    finally:\n        pass"),
    # The independent review's nine.
    ("herestring-word-kept-as-argument", "shell.py", 'if operator.startswith("<<<"):\n            self.target = "herestring"', 'if operator.startswith("<<<"):\n            self.target = ""'),
    ("heredoc-bodies-read-as-commands", "shell.py", 'if operator == "\\n" and self.heredocs:\n            self.skip_heredocs()', 'if operator == "\\n" and self.heredocs:\n            self.heredocs = []'),
    ("python-c-read-as-shell", "guard.py", 'SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})', 'SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "python3"})'),
    ("lessons-none-ignored", "turn.py", "if not section or none:", "if not section:"),
    ("deferred-count-not-kept", "turn.py", "if calls >= min_calls and not is_deferred:", "if calls >= min_calls:"),
    ("count-never-emptied", "turn.py", 'if calls >= min_calls and not is_deferred:\n        write_atomic(calls_path, "")', "if False:\n        pass"),
    ("git-reset-any", "guard.py", 'return subcommand == "reset" and "--hard" in arguments', 'return subcommand == "reset"'),
    ("blocks-not-reset-at-pass", "turn.py", 'write_atomic(blocks_path, "0")\n    if problems:', "if problems:"),
    ("free-prefixes-ignored", "guard.py", "and not script.startswith(policy.free_prefixes)", ""),
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
    ("sleep-allowed", "guard.py", '("sleep", os.path.basename(command.name) == "sleep"),', '("sleep", False),'),
    ("sleep-path-not-reduced", "guard.py", '("sleep", os.path.basename(command.name) == "sleep"),', '("sleep", command.name == "sleep"),'),
    ("sleep-refused-in-background", "guard.py", 'if rule != "sleep" or not is_background]', 'if rule != "sleep" or True]'),
    ("background-drops-every-rule", "guard.py", 'if rule != "sleep" or not is_background]', 'if not is_background]'),
    ("background-flag-any-value", "guard.py", 'tool_input.get("run_in_background") is True,', '"run_in_background" in tool_input,'),
    ("soft-permission-decision-added", "guard.py", 'output: dict = {"hookEventName": "PreToolUse"}', 'output: dict = {"hookEventName": "PreToolUse", "permissionDecision": "allow"}'),
    ("sleep-sequence-branch-for-polling-loop", "guard.py", "return not segment.in_loop and not segment.in_group and", "return not segment.in_group and"),
    ("sleep-sequence-branch-for-subshell", "guard.py", "return not segment.in_loop and not segment.in_group and", "return not segment.in_loop and"),
    ("sleep-sequence-branch-for-nested-string", "guard.py", "flags.append(is_top_level and is_direct_sleep(segment))", "flags.append(is_direct_sleep(segment))"),
    ("sleep-background-flag-not-set", "guard.py", 'return SleepFix({**tool_input, "run_in_background": True}, SLEEP_BACKGROUND_NOTE)', "return SleepFix(dict(tool_input), SLEEP_BACKGROUND_NOTE)"),
    ("soft-hard-message-dropped-beside-soft", "guard.py", "    if not hard:\n        if breaches:", "    if not hard or any(rule in SOFT_RULES for rule in breaches):\n        if breaches:"),
    ("soft-updated-input-loses-fields", "guard.py", '{**tool_input, "command": SLEEP_SHADOW + command}', '{"command": SLEEP_SHADOW + command}'),
    ("soft-background-input-loses-fields", "guard.py", '{**tool_input, "run_in_background": True}', '{"command": command, "run_in_background": True}'),
    ("soft-still-exits-2", "guard.py", "print(json.dumps(make_soft_output(breaches, tool_input, policy)))\n        return 0", "print(json.dumps(make_soft_output(breaches, tool_input, policy)))\n        return 2"),
    ("soft-repo-refused-again", "guard.py", 'SOFT_RULES = ("temporary", "repo", "sleep")', 'SOFT_RULES = ("temporary", "sleep")'),
    ("soft-temporary-refused-again", "guard.py", 'SOFT_RULES = ("temporary", "repo", "sleep")', 'SOFT_RULES = ("repo", "sleep")'),
    ("soft-note-dropped", "guard.py", 'output["additionalContext"] = "\\n".join(notes)', 'output["additionalContext"] = ""'),
    ("push-cluster-not-read", "guard.py", "if is_cluster(argument) and PUSH_DENIED_LETTERS & set(argument[1:]):", "if False:"),
    ("shell-cluster-not-read", "guard.py", 'has_string_option = has_string_option or (is_cluster(argument) and "c" in argument)', 'has_string_option = has_string_option or argument == "-c"'),
    ("shell-value-option-not-skipped", "guard.py", "if argument in SHELL_VALUE_OPTIONS:", "if False:"),
    ("find-exec-not-read", "guard.py", 'if name == "find":\n        return get_find_runs(command.arguments)', 'if False:\n        pass'),
    ("find-execdir-not-read", "guard.py", 'FIND_RUNNERS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})', 'FIND_RUNNERS = frozenset({"-exec", "-ok", "-okdir"})'),
    ("find-ok-not-read", "guard.py", 'FIND_RUNNERS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})', 'FIND_RUNNERS = frozenset({"-exec", "-execdir", "-okdir"})'),
    ("sudo-options-not-skipped", "guard.py", 'index = skip_options(words, index + 1, OPTION_PREFIXES[word])', 'index = index + 1'),
    ("sudo-values-not-skipped", "guard.py", '"sudo": {"-u", "-g",', '"sudo": {"-g",'),
    ("git-value-options-not-skipped", "guard.py", 'GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree",', 'GIT_VALUE_OPTIONS = frozenset({"-C", "-c",'),
    ("eval-not-read", "guard.py", 'if name == "eval":\n        return get_segments(" ".join(arguments))', 'if False:\n        pass'),
    ("uvx-allowed", "guard.py", 'if name in ("pip", "pip3", "uvx"):', 'if name in ("pip", "pip3"):'),
    ("uv-tool-allowed", "guard.py", '"sync", "pip", "tool"}', '"sync", "pip"}'),
    ("python-m-pip-allowed", "guard.py", 'return name.startswith("python") and is_module_pip(arguments)', "return False"),
    ("uv-run-pip-allowed", "guard.py", 'return arguments[index:index + 1] in (["pip"], ["pip3"]) or is_module_pip(arguments[index + 1 :])', "return False"),
    ("mv-source-not-written", "guard.py", 'if name != "mv":\n        return []', "return []"),
    ("mv-source-counts-as-temporary", "guard.py", 'any(is_temporary(path, policy) for path in written)', 'any(is_temporary(path, policy) for path in [*written, *moved])'),
    ("cp-t-not-read", "guard.py", 'targets = get_option_values(arguments, "t", "--target-directory") if name in TARGET_MOVERS else []', "targets = []"),
    ("paths-compared-unresolved", "guard.py", "return os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))", "return os.path.normpath(os.path.join(cwd, os.path.expanduser(path)))"),
    ("scratch-not-normalized", "common.py", "return os.path.realpath(root / scratch) if scratch else \"\"", 'return os.path.join(str(root), scratch) if scratch else ""'),
    ("declare-values-count-as-globs", "guard.py", "not (is_declarer and ASSIGNMENT.match(word.text))", "True"),
    ("matched-glob-refused", "guard.py", 'return next(glob.iglob(resolve_path(text, directory or ""), recursive=True), None) is None', "return True"),
    ("unmatched-glob-allowed", "guard.py", 'return next(glob.iglob(resolve_path(text, directory or ""), recursive=True), None) is None', "return False"),
    ("glob-not-recursive", "guard.py", 'directory or ""), recursive=True)', 'directory or ""), recursive=False)'),
    ("glob-ignores-the-cd", "guard.py", "has_failing_glob(command, directory, globs[1])", "has_failing_glob(command, policy.root, globs[1])"),
    ("option-glob-judged-as-path", "guard.py", 'if text.startswith("-"):\n        return True', "if False:\n        return True"),
    ("expansion-glob-judged-as-path", "guard.py", "if may_have_written or any(character in text for character in UNEXPANDED) or (", "if may_have_written or ("),
    ("unknown-folder-glob-judged", "guard.py", " or (directory is None and not is_absolute(text)):", ":"),
    ("absolute-glob-not-judged", "guard.py", "(directory is None and not is_absolute(text))", "directory is None"),
    ("glob-pattern-option-not-refused", "guard.py", "is_pattern = index > 0 and command.arguments[index - 1].text in pattern_options", "is_pattern = False"),
    ("glob-pattern-options-of-any-command", "guard.py", "pattern_options = GLOB_PATTERN_OPTIONS.get(name, set())", 'pattern_options = {"-name"}'),
    # The project.
    ("project-follows-the-cwd", "common.py", 'Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()', "Path(cwd).resolve()"),
    ("project-ignores-the-cwd", "common.py", 'Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()', 'Path(os.environ.get("CLAUDE_PROJECT_DIR") or "/").resolve()'),
    ("retro-stale-mark-kept", "turn.py", "if text.isdecimal() and text.isascii() and int(text) <= len(items) else 0", "if text.isdecimal() and text.isascii() else 0"),
    ("retro-line-past-the-inbox", "turn.py", "closed = min(get_covered(handled), len(items))", "closed = get_covered(handled)"),
    ("lessons-quoted-refusal-counts", "turn.py", 'REFUSAL.search(str(block.get("content")))', '"Blocked by the harness" in str(block.get("content"))'),
    ("brief-other-types-unchecked", "brief_lint.py", 'required.get(role, required.get("*", []))', "required.get(role, [])"),
    ("budget-star-ignored", "budget.py", 'turns = table.get(role, table.get("*"))', "turns = table.get(role)"),
    ("habits-front-matter-injected", "context.py", 'body = text.split("---", 2)[-1].strip()', "body = text.strip()"),
    ("feedback-retro-every-item", "turn.py", "if len(waiting) < RETRO_ITEMS or not is_mine", "if not is_mine"),
    ("feedback-of-every-session", "turn.py", "or not is_mine or", "or"),
    ("released-ids-still-hold", "turn.py", " or get_covered(released) > seen:", ":"),
    ("feedback-mark-ignored", "turn.py", "waiting = items[seen:]", "waiting = items"),
    ("feedback-mark-not-written", "turn.py", "write_atomic(mark, str(closed))", "pass"),
    ("feedback-item-line-closes-retro", "turn.py", "if (match := RETRO_KEY.fullmatch(key))", "if (match := re.fullmatch(r'\\w*?-?([0-9]+)', key))"),
    ("feedback-running-agent-holds", "turn.py", "if open_ids and count_running_agents(transcript) > 0:", "if False:"),
    ("feedback-problems-any-role", "context.py", "if owner in (role, \"all\")]", "]"),
    ("feedback-problems-not-for-all", "context.py", "if owner in (role, \"all\")]", "if owner == role]"),
    ("feedback-problems-no-cap", "context.py", "lines = problems[:MAX_PROBLEMS]", "lines = problems"),
    ("lessons-refusal-ignored", "turn.py", "if has_refusal(transcript) and", "if False and"),
    ("lessons-reason-ignored", "turn.py", "and len(tail.split()) < MIN_REASON_WORDS:", ":"),
    ("lessons-old-refusal-counts", "turn.py", "if text.strip() and not APP_PROMPT.search(text[:APP_PROMPT_HEAD]):\n            return False", "if False:\n            return False"),
    ("feedback-same-reason-allowed", "turn.py", 'if owner != item_id else ""', 'if False else ""'),
    ("feedback-problems-not-told", "context.py", ", get_open_problems(root, agent_type))", ")"),
    ("unterminated-fence-hides", "common.py", 'return [line for index, line in enumerate(lines) if index not in fenced]', 'return [line for index, line in enumerate(lines) if index not in fenced and (opened < 0 or index < opened)]'),
    # The report form.
    ("report-length-not-checked", "report_gate.py", "    if count <= limit:\n        return []", "    if True:\n        return []"),
    ("report-length-counts-fences", "report_gate.py", 'count = len("\\n".join(get_unfenced_lines(report)))', "count = len(report)"),
    ("report-length-limit-ignored", "report_gate.py", "check_length(report, get_max_chars(settings))", "check_length(report, MAX_REPORT_CHARS)"),
    ("report-order-not-checked", "report_gate.py", "if name != expected]", "if False]"),
    ("report-required-not-checked", "report_gate.py", "for heading in REQUIRED if heading not in names]", "for heading in REQUIRED if False]"),
    ("report-optional-required", "report_gate.py", 'REQUIRED = ("Answer", "Not proven", "Verdict")', "REQUIRED = ORDER"),
    ("report-unknown-heading-allowed", "report_gate.py", "if name not in ORDER]", "if False]"),
    ("report-duplicate-allowed", "report_gate.py", "if names.count(heading) > 1]", "if False]"),
    ("report-verdict-not-last-allowed", "report_gate.py", 'if "Verdict" in names and names[-1] != "Verdict":', "if False:"),
    ("report-empty-section-allowed", "report_gate.py", 'problems.append(Problem(heading, f"{heading} is empty"))', "pass"),
    ("report-none-problems-refused", "report_gate.py", 'case "Problems" if not is_none(lines):', 'case "Problems":'),
    ("report-answer-none-allowed", "report_gate.py", 'case "Answer" if is_none(lines):', 'case "Answer" if False:'),
    ("report-verdict-word-unchecked", "report_gate.py", 'case "Verdict" if not VERDICT.match(item_text(text)):', 'case "Verdict" if False:'),
    ("report-verdict-needs-no-sentence", "report_gate.py", r'(done|partial|blocked)\b\W*(\S.*)"', r'(done|partial|blocked)\b\W*(\S*.*)"'),
    ("report-verdict-case-matters", "report_gate.py", r'(\S.*)", re.I | re.S)', r'(\S.*)", re.S)'),
    ("report-bare-not-proven-allowed", "report_gate.py", 'case "Not proven" if len(item_text(text).split()) < MIN_NOT_PROVEN_WORDS:', 'case "Not proven" if False:'),
    ("report-not-proven-two-words-pass", "report_gate.py", "MIN_NOT_PROVEN_WORDS = 3", "MIN_NOT_PROVEN_WORDS = 2"),
    ("report-not-proven-four-words-needed", "report_gate.py", "MIN_NOT_PROVEN_WORDS = 3", "MIN_NOT_PROVEN_WORDS = 4"),
    ("report-problem-cause-unchecked", "report_gate.py", "if not cause_pattern.search(item):", "if False:"),
    ("report-problem-helped-unchecked", "report_gate.py", 'if "helped" not in item.lower():', "if False:"),
    ("report-problems-first-item-only", "report_gate.py", "for item in get_items(lines):\n        if not cause_pattern", "for item in get_items(lines)[:1]:\n        if not cause_pattern"),
    ("report-ledger-verdict-dropped", "report_gate.py", '"verdict": verdict.group(1).lower() if verdict else None,', '"verdict": None,'),
    ("report-ledger-verdict-case", "report_gate.py", "verdict.group(1).lower()", "verdict.group(1)"),
    ("report-ledger-verdict-guessed", "report_gate.py", "if verdict else None,", 'if verdict else "done",'),
    ("feedback-item-needs-no-file", "report_gate.py", "and not FILE_NAME.search(text)]", "and False]"),
    ("feedback-item-continuation-lost", "report_gate.py", "items[-1] += \" \" + line.strip()", "pass"),
    ("auto-open-items-filed", "report_gate.py", '.get("Feedback", [])', '.get("Open", [])'),
    ("auto-problems-filed", "report_gate.py", '.get("Feedback", [])', '.get("Problems", [])'),
    ("exit-pass-claim-not-checked", "report_gate.py", "if pass_claim and not has_bash:", "if False:"),
    ("exit-pass-claim-only-passed", "report_gate.py", "(pass(?:es|ed)?|clean|green)", "(pass(?:es|ed)?)"),
    ("exit-pass-claim-only-tests", "report_gate.py", r"\b(tests?|lint|checks?|gates?|build)\b", r"\b(tests?)\b"),
    ("commit-subject-unchecked", "commit_gate.py", 'if not SUBJECT.match(subject):', 'if False:'),
    ("commit-any-type", "commit_gate.py", '(feat|fix|perf|refactor|test|docs|style|build|ci|chore|revert)', '\\w+'),
    ("commit-period-allowed", "commit_gate.py", 'if subject.rstrip().endswith("."):', 'if False:'),
    ("commit-no-bullets-allowed", "commit_gate.py", 'if not any(line.startswith(BULLETS) for line in body):', 'if False:'),
    ("commit-no-blank-line-allowed", "commit_gate.py", 'if lines and lines[0].strip():', 'if False:'),
    ("commit-stray-line-allowed", "commit_gate.py", 'return [f"this body line is no bullet: {stray[0][:60]}"] if stray else []', 'return []'),
    ("commit-footer-refused", "commit_gate.py", ' and not FOOTER.match(line)', ''),
    ("commit-continuation-refused", "commit_gate.py", 'line.startswith((*BULLETS, " ", "\\t"))', 'line.startswith(BULLETS)'),
    ("commit-attribution-allowed", "commit_gate.py", 'if AI_ATTRIBUTION.search(message) else []', 'if False else []'),
    ("commit-generated-allowed", "commit_gate.py", 'generated (with|by)[^\\n]*{AI_NAME}|', ''),
    ("commit-robot-allowed", "commit_gate.py", '|\\U0001f916', ''),
    ("commit-any-coauthor-refused", "commit_gate.py", 'co-authored-by:[^\\n]*{AI_NAME}', 'co-authored-by:'),
    ("commit-git-subject-judged", "commit_gate.py", 'if GIT_SUBJECT.match(subject):', 'if False:'),
    ("budget-empty-transcript-crashes", "budget.py", "    except ValueError:\n        first = {}\n", "    except KeyError:\n        first = {}\n"),
    ("retro-other-digits-crash", "turn.py", "if text.isdecimal() and text.isascii() and int(text) <= len(items)", "if text.isdigit() and int(text) <= len(items)"),
    ("config-list-crashes", "common.py", "sections = config.items() if isinstance(config, dict) else ()", "sections = config.items()"),
    ("commit-first-heredoc-read", "commit_gate.py", "HEREDOC.search(command, get_tail_start(command))", "HEREDOC.search(command)"),
    ("commit-later-command-judged", "commit_gate.py", 'problems += check_attribution("\\n".join(get_option_value(words, "--trailer")))', "problems += check_attribution(command)"),
    ("commit-pr-unreadable-body-allowed", "commit_gate.py", "body if body is not None else get_text_up_to_call(command)", 'body or ""'),
    ("commit-trailer-option-allowed", "commit_gate.py", 'problems += check_attribution("\\n".join(get_option_value(words, "--trailer")))', "pass"),
    ("commit-variable-trailer-allowed", "commit_gate.py", "if message is not None else check_attribution(get_text_up_to_call(command))", "if message is not None else []"),
    ("commit-unreadable-scans-later-steps", "commit_gate.py", "return command[: end.start()] if end else command", "return command"),
    ("commit-pr-edit-unchecked", "commit_gate.py", 'words[2:3] in (["create"], ["edit"])', 'words[2:3] == ["create"]'),
    ("guard-dry-run-refused", "guard.py", " and not is_dry_run", ""),
    ("turn-stopped-agent-runs-on", "turn.py", '"killed", "stopped"}', '"killed"}'),
    ("config-bad-section-crashes", "common.py", "{key: value if isinstance(value, dict) else {} for key, value in sections}", "dict(sections)"),
    ("context-no-habits-fallback", "context.py", "return HABITS_FALLBACK\n    body", 'return ""\n    body'),
    ("stop-headings-ignored", "turn.py", 'settings.get("headings", HEADINGS)', "HEADINGS"),
    ("delegate-git-options-refused", "delegate.py", 'while words[:1] == ["git"] and words[1:2] in (["-C"], ["-c"]):', "while False:"),
        ("commit-heredoc-unread", "commit_gate.py", 'return heredoc.group(2) if heredoc else None', 'return None'),
    ("commit-file-unread", "commit_gate.py", 'return file.read()', 'return None'),
    ("commit-cluster-unread", "commit_gate.py", ' or (letter and word.startswith("-") and not word.startswith("--") and word.endswith(letter))', ' or word == f"-{letter}"'),
    ("commit-long-equals-unread", "commit_gate.py", 'elif word.startswith(f"{long_name}="):', 'elif False:'),
    ("commit-values-not-joined", "commit_gate.py", 'return "\\n\\n".join(values)', 'return values[0]'),
    ("commit-other-git-judged", "commit_gate.py", 'and get_git_subcommand(words[1:]) == "commit":', ':'),
    ("commit-git-options-missed", "commit_gate.py", 'get_git_subcommand(words[1:]) == "commit"', 'words[1:2] == ["commit"]'),
    ("commit-pr-unchecked", "commit_gate.py", 'elif name == "gh" and words[1:2] == ["pr"]', "elif False"),
    ("commit-no-off-switch", "commit_gate.py", ' or config.get("guard", {}).get("commit_style") is False', ''),
    ("commit-bug-blocks", "commit_gate.py", 'sys.exit(1)', 'sys.exit(2)'),
    ("report-agent-prefix-kept", "report_gate.py", 'name = (event.get("agent_type") or "").removeprefix(PLUGIN_PREFIX)', 'name = (event.get("agent_type") or "")'),
    ("report-missing-form-only-for-workers", "report_gate.py", "problems = check_headings(sections)", 'problems = check_headings(sections) if name == "worker" else []'),
    # The report gate.
    ("user-lines-count", "report_gate.py", 'if entry.get("type") == "assistant":\n                    blocks.append(block)', "if True:\n                    blocks.append(block)"),
    ("any-heading-is-the-report", "report_gate.py", "if heading.search(last):", 'if "## " in last:'),
    ("first-report-wins", "report_gate.py", "if isinstance(text, str) and heading.search(text):\n            report = text", "if isinstance(text, str) and heading.search(text) and not report:\n            report = text"),
    ("handback-not-read", "report_gate.py", 'is_handback = block.get("type") == "tool_use" and block.get("name") == HANDBACK_TOOL', "is_handback = False"),
    ("changed-files-not-checked", "report_gate.py", "if not is_exempt and not is_named(path, report, folders):", "if False:"),
    ("scratch-not-exempt", "report_gate.py", "is_exempt = scratch and (path == scratch or path.startswith(scratch + os.sep))", "is_exempt = False"),
    ("failed-edit-counts", "report_gate.py", 'and block.get("id") not in failed:', ":"),
    ("notebook-edit-ignored", "common.py", 'EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})', 'EDIT_TOOLS = frozenset({"Edit", "Write"})'),
    ("named-by-substring", "report_gate.py", 'return re.search(rf"(?<![\\w./-])(?:\\./)?(?:{pattern})(?![\\w/-]|\\.\\w)", report) is not None', "return any(spelling in report for spelling in spellings)"),
    ("exit-claim-not-checked", "report_gate.py", "if exit_claim and not has_bash:", "if False:"),
    ("read-claim-not-checked", "report_gate.py", "problems = check_read_claims(report, root)", "problems = []"),
    ("read-range-checks-its-start", "report_gate.py", "line = int(last or first)", "line = int(first)"),
    ("read-missing-file-allowed", "report_gate.py", 'problems.append(Problem(section, f"READ names a file that does not exist: {path}"))', "pass"),
    ("no-feedback-words-filed", "report_gate.py", 'NO_FEEDBACK = re.compile(r"(none|none needed|no feedback|n/?a)[ .]*", re.I)', 'NO_FEEDBACK = re.compile(r"(none)[ .]*", re.I)'),
    ("inbox-line-without-session", "report_gate.py", 'f"- id={item_id} session={session} agent={role} {text}\\n"', 'f"- id={item_id} agent={role} {text}\\n"'),
    ("known-item-across-sessions", "report_gate.py", 'if f"id={item_id} session={session} " not in known:', 'if f"id={item_id} " not in known:'),
    # The turn.
    ("released-ids-not-saved", "turn.py", 'write_atomic(released_path, " ".join(sorted(released | set(open_ids))))', "pass"),
    ("worktree-counts-as-a-rule", "turn.py", "and not (is_claude and name == WORKTREES[1])", ""),
    ("any-status-after-the-id-finishes", "turn.py", "for tool_id, status in found if status in FINISHED_STATUSES", "for tool_id, status in found"),
    ("reset-empties-a-deferred-count", "turn.py", 'if not is_app_prompt and not get_state_path(event.get("session_id") or "unknown", "deferred").exists():', "if not is_app_prompt:"),
    ("deferred-mark-not-written", "turn.py", 'write_atomic(deferred_path, "1")', "pass"),
    ("deferred-mark-not-cleared", "turn.py", "if not is_deferred and deferred_path.exists():\n        deferred_path.unlink()", "if False:\n        pass"),
    # The main_edits cap.
    ("main-edits-cap-off-by-one", "delegate.py", "if count >= maximum:", "if count > maximum:"),
    ("main-edits-allowed-counted", "delegate.py", "return not any(fnmatch.fnmatch(relative, pattern) for pattern in allow)", "return True"),
    ("main-edits-sub-agent-counted", "delegate.py", '    if event.get("agent_id"):\n        return 0\n    cwd', "    cwd"),
    ("main-edits-zero-not-off", "delegate.py", "or maximum <= 0:", ":"),
    ("main-edits-agent-lines-counted", "delegate.py", "if name in EDIT_TOOLS and edited and", "if edited and"),
    ("main-edits-max-ignored", "delegate.py", 'maximum = settings.get("max", DEFAULT_MAX_EDITS)', "maximum = DEFAULT_MAX_EDITS"),
    ("main-edits-allow-ignored", "delegate.py", 'allow = settings.get("allow", list(DEFAULT_EDIT_ALLOW))', "allow = list(DEFAULT_EDIT_ALLOW)"),
    ("main-edits-note-dropped", "delegate.py", "notes = [note for note in (check_delegate(event, root, config, cwd), edit_note) if note]", "notes = [note for note in (check_delegate(event, root, config, cwd),) if note]"),
    ("main-edits-not-a-default-section", "common.py", 'DEFAULT_SECTIONS = ("brief", "skill_gate", "main_edits")', 'DEFAULT_SECTIONS = ("brief", "skill_gate")'),
    ("add-drops-the-edit-path", "turn.py", 'if name in EDIT_TOOLS and isinstance(path, str) and path:', "if False:"),
    ("add-drops-notebook-path", "turn.py", 'path = tool_input.get("file_path") or tool_input.get("notebook_path")', 'path = tool_input.get("file_path")'),
    ("check-agents-reads-every-tab-line", "turn.py", 'if line.split("\\t", 1)[0] in AGENT_TOOLS and "\\t" in line]', 'if "\\t" in line]'),
    ("launch-text-from-any-result", "turn.py", 'block.get("tool_use_id") in agent_calls and "Async agent launched"', 'True and "Async agent launched"'),
    # The delegate rule.
    ("delegate-judges-sub-agents", "delegate.py", '    if event.get("agent_id"):\n        return 0\n', ""),
    ("delegate-without-its-key", "delegate.py", 'if "delegate" not in config:', "if False:"),
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
    ("budget-default-wins", "budget.py", "    if limit is None and (has_project_file(root) or agent_type.startswith(PLUGIN_PREFIX)):\n", "    if True:\n"),
    ("budget-defaults-ignore-config", "budget.py", 'table = config.get("budget", DEFAULT_BUDGET)\n', "table = DEFAULT_BUDGET\n"),
    ("budget-unknown-role-gets-a-budget", "budget.py", 'turns = table.get(role, table.get("*"))', "turns = table.get(role, 1)"),
    ("budget-fence-read", "budget.py", "for line in get_unfenced_lines(brief):", "for line in brief.splitlines():"),
    ("budget-turns-word-refused", "budget.py", "(?:turns?\\b|(?=\\W*$))", "(?=\\W*$)"),
    ("budget-any-number-counts", "budget.py", "|(?=\\W*$))", "|)"),
    ("budget-line-must-fill-the-line", "budget.py", "BUDGET_LINE.search(", "BUDGET_LINE.fullmatch("),
    ("budget-quote-counts", "budget.py", 'QUOTED.sub("", line)', "line"),
    ("budget-prose-counts", "budget.py", '(?:^|[.;]\\s+)[\\s\\-*#]*budget', "budget"),
    ("budget-refuses-the-handback", "budget.py", ' or event.get("tool_name") == HANDBACK_TOOL', ""),
    ("budget-list-brief-ignored", "budget.py", "if isinstance(content, list):", "if False:"),
    ("budget-message-silent", "budget.py", "Send your report now as a partial report: done, not done, what is on disk.", "Stop."),
    ("budget-prefix-kept", "budget.py", "get_default(config, agent_type.removeprefix(PLUGIN_PREFIX))", "get_default(config, agent_type)"),
    ("budget-bug-blocks", "budget.py", "sys.exit(1)", "sys.exit(2)"),
    ("ledger-duration-dropped", "report_gate.py", '"duration_s": duration,', '"duration_s": None,'),
    ("ledger-duration-from-first-only", "budget.py", "round(last - first, 1)", "0.0"),
    # The brief rule.
    ("feedback-written-into-repo", "common.py", "    if has_project_file(root):\n        return root\n\n    return data_folder()", "    return root\n\n    return data_folder()"),
    ("repo-agent-report-gated", "report_gate.py", "if not is_judged(root, event):", "if False:"),
    ("repo-agent-default-budget", "budget.py", "if limit is None and (has_project_file(root) or agent_type.startswith(PLUGIN_PREFIX)):", "if limit is None:"),
    ("retro-without-project-file", "turn.py", "    if has_project_file(root):\n        problems += check_lessons", "    if True:\n        problems += check_lessons"),
    ("owner-file-ignored", "common.py", "if key in template}, owner)", "if key in template})"),
    ("transcript-non-object-kept", "turn.py", "            if isinstance(event, dict):\n                lines.append(event)", "            lines.append(event)"),
    ("guard-curl-output-unread", "guard.py", 'outputs = get_option_values(arguments, "o", "--output")', "outputs = []"),
    ("guard-notebook-path-unread", "guard.py", 'tool_input.get("file_path") or tool_input.get("notebook_path")', 'tool_input.get("file_path")'),
    ("broken-owner-file-raises", "common.py", "    except (OSError, ValueError):\n        owner = {}", "    except ZeroDivisionError:\n        owner = {}"),
    ("owner-file-beats-project", "common.py", "return Project(candidate, merge_sections(base, read_sections(path)))", "return Project(candidate, merge_sections(read_sections(path), base))"),
    ("defaults-dropped", "common.py", 'DEFAULT_SECTIONS = ("brief", "skill_gate", "main_edits")', "DEFAULT_SECTIONS = ()"),
    ("guard-rules-without-project-file", "guard.py", "    if not has_project_file(root):\n        return Policy()\n", ""),
    ("commit-rule-without-project-file", "commit_gate.py", "if not has_project_file(root) or ", "if "),
    ("brief-generic-allowed", "brief_lint.py", "if agent_type in GENERIC_AGENTS:", "if False:"),
    ("brief-no-type-allowed", "brief_lint.py", 'GENERIC_AGENTS = frozenset({"", "general-purpose"', 'GENERIC_AGENTS = frozenset({"general-purpose"'),
    ("brief-judges-sub-agents", "brief_lint.py", '    if event.get("agent_id"):\n        return 0\n', ""),
    ("brief-without-its-key", "brief_lint.py", 'if "brief" not in config:\n        return 0\n', ""),
    ("brief-generic-needs-its-key", "brief_lint.py", '    agent_type = tool_input.get("subagent_type") or ""\n', '    if "brief" not in config:\n        return 0\n    agent_type = tool_input.get("subagent_type") or ""\n'),
    ("brief-prefix-not-removed", "brief_lint.py", '.removeprefix(PLUGIN_PREFIX)', ""),
    ("brief-reviewer-unchecked", "brief_lint.py", '    "reviewer": ["Goal:", "Input:", "Tree:"],\n', ""),
    ("brief-auditor-unchecked", "brief_lint.py", '    "auditor": ["Goal:", "Input:", "Judge:"],\n', ""),
    ("brief-runner-unchecked", "brief_lint.py", '    "runner": ["Goal:", "Runs:"],\n', ""),
    ("brief-plan-allowed", "brief_lint.py", 'frozenset({"", "general-purpose", "Explore", "Plan", "claude"})', 'frozenset({"", "general-purpose", "Explore", "claude"})'),
    ("brief-explore-allowed", "brief_lint.py", 'frozenset({"", "general-purpose", "Explore", "Plan", "claude"})', 'frozenset({"", "general-purpose", "Plan", "claude"})'),
    ("guard-unlink-allowed", "guard.py", 'DELETERS = frozenset({"rm", "rmdir", "unlink", "shred"})', 'DELETERS = frozenset({"rm", "rmdir", "shred"})'),
    ("guard-find-delete-allowed", "guard.py", 'return "-delete" in arguments', "return False"),
    ("guard-pushd-unmoved", "guard.py", 'DIRECTORY_CHANGERS = frozenset({"cd", "pushd", "popd"})', 'DIRECTORY_CHANGERS = frozenset({"cd", "popd"})'),
    ("guard-popd-unmoved", "guard.py", 'DIRECTORY_CHANGERS = frozenset({"cd", "pushd", "popd"})', 'DIRECTORY_CHANGERS = frozenset({"cd", "pushd"})'),
    ("guard-wget-default-dropped", "guard.py", 'return get_option_values(arguments, "P", "--directory-prefix") or ["."]', "return []"),
    ("guard-wget-prefix-ignored", "guard.py", 'return get_option_values(arguments, "P", "--directory-prefix") or ["."]', 'return ["."]'),
    ("brief-required-ignored", "brief_lint.py", '(config["brief"] or {}).get("required", DEFAULT_REQUIRED)', "DEFAULT_REQUIRED"),
    ("brief-worker-needs-no-judge", "brief_lint.py", '"worker": ["Goal:", "Write set:", "Judge:"]', '"worker": ["Goal:", "Write set:"]'),
    ("brief-label-anywhere", "brief_lint.py", "any(line.startswith(label) for line in lines)", "any(label in line for line in lines)"),
    ("brief-bold-label-refused", "brief_lint.py", 'LINE_MARKS = " \\t-*#"', 'LINE_MARKS = " \\t"'),
    # The handback and the glob rule's exceptions.
    ("gate-sends-back-an-ended-agent", "report_gate.py", 'bool(found.blocks) and found.blocks[-1].get("name") == HANDBACK_TOOL or ', ""),
    ("gate-no-report-sent-back", "report_gate.py", ' or (os.path.isfile(path) and not sent)', ""),
    ("gate-every-agent-has-ended", "report_gate.py", "if has_ended or tries >= MAX_SEND_BACKS:", "if True:"),
    ("glob-judged-in-any-shell", "guard.py", 'os.path.basename(os.environ.get("SHELL") or "") == "zsh"', "True"),
    ("glob-judged-in-bash-c", "guard.py", 'judges_globs and not (name in SHELLS and name != "zsh")', "judges_globs"),
    ("glob-never-judged-in-zsh-c", "guard.py", 'name in SHELLS and name != "zsh"', "name in SHELLS"),
    ("glob-judged-after-a-write", "guard.py", "if may_have_written or any(", "if any("),
    ("glob-skipped-after-a-read", "guard.py", "may_have_written or name not in READ_ONLY_COMMANDS", "True"),
    ("glob-redirect-is-no-write", "guard.py", " or bool(get_written_words(segment, command, directory))", ""),
    ("glob-fix-dropped", "guard.py", 'messages["glob"] += f"\\nRun instead: {shown}"', "pass"),
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
    # The import and replay tools.
    ("import-known-ledger-ignored", "import_reports.py", "    if ledger.is_file():\n        for line", "    if False:\n        for line"),
    ("import-known-agent-added-again", "import_reports.py", 'if row["agent_id"] in known:', "if False:"),
    ("import-report-card-optional", "import_reports.py", '    if "REPORT CARD" not in sections:\n        return None\n    scores = get_scores(sections["REPORT CARD"])', '    scores = get_scores(sections.get("REPORT CARD", []))'),
    ("import-dry-run-writes", "import_reports.py", "if rows and not args.dry_run and ledger:", "if rows and ledger:"),
    ("import-ledger-newline-not-joined", "import_reports.py", "if lacks_newline:", "if False:"),
    ("replay-soft-rule-refused", "replay.py", "(noted if rule in SOFT_RULES else refused)[rule]", "refused[rule]"),
    ("replay-command-counted-per-session", "replay.py", "distinct.add(call)", 'distinct.add((call[0], f"{call[1]}{path}", call[2]))'),
    ("replay-glob-folder-unknown", "replay.py", "find_command_breaches(command, cwd, Policy(), is_background=is_background)", "find_command_breaches(command, None, Policy(), is_background=is_background)"),
    ("replay-glob-judged-in-the-root", "replay.py", "find_command_breaches(command, cwd, Policy(), is_background=is_background)", 'find_command_breaches(command, "/", Policy(), is_background=is_background)'),
    # The tool-turn nudge.
    ("nudge-run-long", "nudge.py", "RUN_LENGTH = 3", "RUN_LENGTH = 4"),
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
    ("pipe-pipefail-ignored", "nudge.py", "    if PIPEFAIL.search(command):\n", "    if False:\n"),
    ("pipe-pipestatus-ignored", "nudge.py", "    if ZSH_STATUS.search(command) or BASH_STATUS.search(command):\n", "    if BASH_STATUS.search(command):\n"),
    ("pipe-any-command-is-a-gate", "nudge.py", "any(is_gate(earlier) for earlier in pieces[:index])", "True"),
    ("pipe-any-sink", "nudge.py", "os.path.basename(words[0]) in PIPE_SINKS and", "bool(words) and"),
    ("pipe-list-not-split", "nudge.py", 'LIST_SPLIT = re.compile(r"&&|\\|\\||[;\\n]")', 'LIST_SPLIT = re.compile(r"(?!)")'),
    ("pipe-quotes-read", "nudge.py", 'QUOTED = re.compile(r"\'[^\']*\'|\\"[^\\"]*\\"")', 'QUOTED = re.compile(r"(?!)")'),
    ("pipe-every-call-hears", "nudge.py", "if pipe_nudge and pipe_nudge[0] == call_id:", "if pipe_nudge:"),
    ("pipe-zsh-note-in-any-shell", "nudge.py", 'os.path.basename(os.environ.get("SHELL") or "") == "zsh" and BASH_STATUS', "BASH_STATUS"),
    ("pipe-bash-status-unread", "nudge.py", "or BASH_STATUS.search(command):\n        return", "or False:\n        return"),
    ("nudge-bug-blocks", "nudge.py", "sys.exit(1)", "sys.exit(2)"),
    ("ledger-tool-turns-lost", "report_gate.py", "get_turn_stats(read_events(path)) if path else None", "None"),
    # The context hook.
    ("context-session-silent", "context.py", "(SESSION_TEXT, habits,", '("", habits,'),
    ("context-tool-turns-not-for-session", "context.py", "(SESSION_TEXT, habits,", "(SESSION_TEXT,"),
    ("context-form-silent", "context.py", "(FORM_TEXT, habits, get_setup_text(config), get_lessons", '("", habits, get_setup_text(config), get_lessons'),
    ("context-form-only-for-workers", "context.py", "(FORM_TEXT, habits, get_setup_text(config), get_lessons", '(FORM_TEXT if agent_type == "harness:worker" else "", habits, get_setup_text(config), get_lessons'),
    ("context-form-for-session", "context.py", "(SESSION_TEXT, habits,", "(SESSION_TEXT, FORM_TEXT, habits,"),
    ("context-tool-turns-not-for-agents", "context.py", "(FORM_TEXT, habits, get_setup_text(config), get_lessons", "(FORM_TEXT, get_setup_text(config), get_lessons"),
    # The report gate's claim and auto-item rules.
    ("exit-claim-matches-any-code", "report_gate.py", "if code not in seen and not re.search(PRINTED_EXIT", "if False and not re.search(PRINTED_EXIT"),
    ("failed-call-counts-as-exit-zero", "report_gate.py", "            if call_id not in failed:\n                seen.add(0)", "            if True:\n                seen.add(0)"),
    ("read-quote-not-checked", "report_gate.py", "if not all(part in window for part in parts if part):", "if False:"),
    ("read-quote-searches-the-whole-file", "report_gate.py", "lines[first_line : line + QUOTE_WINDOW]", "lines"),
    # The turn's handled-line check.
    ("handled-file-missing-accepted", "turn.py", "if not path.is_file():", "if False:"),
    ("handled-file-unchanged-accepted", "turn.py", "if saved.get(str(path)) == state[str(path)]:", "if False:"),
    ("handled-file-not-a-rule-accepted", "turn.py", "if str(path) not in state:", "if False:"),
    ("handled-no-file-named-accepted", "turn.py", "if not name:\n        return", "if False:\n        return"),
    ("rejected-reason-length-ignored", "turn.py", "is_short = len(reason.split()) < MIN_REASON_WORDS", "is_short = False"),
    ("rejected-two-words-pass", "turn.py", "MIN_REASON_WORDS = 3", "MIN_REASON_WORDS = 2"),
    # The skill gate.
    ("skill-gate-commit-unseen", "skill_gate.py", '            needs[COMMIT_SKILL] = "committing"', "            pass"),
    ("skill-gate-git-options-missed", "skill_gate.py", 'get_git_subcommand(arguments) == "commit"', 'arguments[:1] == ["commit"]'),
    ("skill-gate-pr-unseen", "skill_gate.py", ' or (name == "gh" and arguments[:1] == ["pr"] and arguments[1:2] in (["create"], ["edit"]))', ""),
    ("skill-gate-shell-writes-unseen", "skill_gate.py", "files += get_written_words(segment, call, cwd)", "pass"),
    ("skill-gate-scripts-unseen", "skill_gate.py", "files = get_script_files(command)", "files = []"),
    ("skill-gate-any-heredoc-is-a-script", "skill_gate.py", '"python" in match.group(1) and ', ""),
    ("skill-gate-read-script-judged", "skill_gate.py", " and SCRIPT_WRITE.search(match.group(3))", ""),
    ("skill-gate-write-text-unseen", "skill_gate.py", '\\.write_text\\(|', ""),
    ("guard-scratch-delete-refused", "guard.py", "is_delete(command) and not is_scratch_delete(command, directory, policy)", "is_delete(command)"),
    ("guard-scratch-itself-deleted", "guard.py", ".startswith(policy.scratch + os.sep) for word in paths]", ".startswith(policy.scratch) for word in paths]"),
    ("guard-scratch-glob-deleted", "guard.py", "all(not word.is_glob and", "all("),
    ("guard-scratch-variable-deleted", "guard.py", ' and "$" not in word.text', ""),
    ("guard-scratch-shred", "guard.py", "SCRATCH_DELETERS = frozenset({\"rm\", \"rmdir\"})", "SCRATCH_DELETERS = DELETERS"),
    ("commit-dash-bullets-refused", "commit_gate.py", 'BULLETS = ("* ", "- ")', 'BULLETS = ("* ",)'),
    ("skill-gate-nothing-injected", "skill_gate.py", "    if missing:\n        plugin = ", "    if False:\n        plugin = "),
    ("skill-text-not-injected", "skill_gate.py", 'if text else ""', 'if False else ""'),
    ("skill-frontmatter-left-in", "skill_gate.py", '_, _, text = text[4:].partition("\\n---\\n")', "pass"),
    ("skill-marker-ignored", "skill_gate.py", "if MARKER.encode() in line:", "if False:"),
    ("skill-cap-ignored", "skill_gate.py", "if piece and used + len(piece) <= MAX_INJECTED:", "if piece:"),
    ("skill-name-with-a-path-read", "skill_gate.py", 'or not re.fullmatch(r"[\\w-]+", name) ', ""),
    ("skill-unprefixed-name-read", "skill_gate.py", "if not skill.startswith(PLUGIN_PREFIX) or ", "if "),
    ("skill-gate-exits-2", "skill_gate.py", "print(json.dumps(make_note_output(make_context(missing, plugin))))\n\n    return 0", "print(json.dumps(make_note_output(make_context(missing, plugin))))\n\n    return 2"),
    ("brief-permission-decision-added", "brief_lint.py", "get_unfenced_lines, make_note_output\n", 'get_unfenced_lines, make_note_output\n\nmake_plain_note = make_note_output\n\n\ndef make_note_output(note):\n    output = make_plain_note(note)\n    output["hookSpecificOutput"]["permissionDecision"] = "allow"\n    return output\n'),
    ("delegate-permission-decision-added", "delegate.py", "find_project, make_note_output\n", 'find_project, make_note_output\n\nmake_plain_note = make_note_output\n\n\ndef make_note_output(note):\n    output = make_plain_note(note)\n    output["hookSpecificOutput"]["permissionDecision"] = "allow"\n    return output\n'),
    ("brief-still-exits-2", "brief_lint.py", "make_note_output(\"\\n\".join(f\"The harness brief rule let this call run: {note}\" for note in notes))))\n\n    return 0", "make_note_output(\"\\n\".join(f\"The harness brief rule let this call run: {note}\" for note in notes))))\n\n    return 2"),
    ("delegate-still-exits-2", "delegate.py", "\" \".join(notes))))\n\n    return 0", "\" \".join(notes))))\n\n    return 2"),
    ("brief-note-dropped", "brief_lint.py", "    if notes:\n", "    if False:\n"),
    ("delegate-note-dropped", "delegate.py", 'print(json.dumps(make_note_output(" ".join(notes))))', 'print(json.dumps(make_note_output("")))'),
    ("skill-gate-scratch-not-exempt", "skill_gate.py", "is_scratch = scratch and (absolute == scratch", "is_scratch = False and (absolute == scratch"),
    ("skill-gate-bare-name-refused", "skill_gate.py", "return skill.removeprefix(PLUGIN_PREFIX)", "return skill"),
    ('skill-gate-reads-the-session-transcript', "skill_gate.py", 'if event.get("agent_id"):\n        return get_agent_path(event)', 'if False:\n        return get_agent_path(event)'),
    # The report gate after a send-back.
    ("report-merge-drops-a-section-not-resent", "report_gate.py", "    kept = [(heading, lines) for heading, lines in old_sections if heading in ORDER and heading not in resent]", "    kept = []"),
    ("report-merge-keeps-old-over-new", "report_gate.py", "if heading in ORDER and heading not in resent]", "if heading in ORDER]"),
    ("report-merge-keeps-the-new-over-nothing", "report_gate.py", "    merged = sorted([*kept, *new_sections]", "    merged = sorted([*kept]"),
    ("report-merge-keeps-a-stray-section", "report_gate.py", "if heading in ORDER and heading not in resent]", "if heading not in resent]"),
    ("report-merge-unsorted", "report_gate.py", "merged = sorted([*kept, *new_sections], key=lambda section: ORDER.index(section[0]) if section[0] in ORDER else len(ORDER))", "merged = [*kept, *new_sections]"),
    ("report-merge-loses-the-title", "report_gate.py", "preamble = new_preamble if REPORT_TITLE.search", "preamble = new_preamble if True or REPORT_TITLE.search"),
    ("report-send-back-names-sections-that-are-fine", "report_gate.py", "wrong = list(dict.fromkeys(problem.section for problem in problems))", "wrong = list(ORDER)"),
    ("report-send-back-asks-every-hint", "report_gate.py", "advice = \" \".join(hints[section] for section in wrong if section in hints)", "advice = \" \".join(hints.values())"),
    ("report-claim-section-guessed", "report_gate.py", 'return heading if heading in ORDER else "Answer"', 'return "Answer"'),
    ("report-resend-needs-an-answer-heading", "report_gate.py", "heading = SECTION_HEADING if is_resend else ANSWER_HEADING", "heading = ANSWER_HEADING"),
    ("report-kept-never-saved", "report_gate.py", 'write_atomic(get_kept_path(event), json.dumps({"raw": sent, "merged": report}))', "pass"),
    ("report-kept-stays-after-stop", "report_gate.py", "for stale in (path, get_kept_path(event)):", "for stale in (path,):"),
    ("report-kept-used-without-a-send-back", "report_gate.py", "if not tries or not path.exists():", "if not path.exists():"),
    ("report-judged-message-awaited-no-more", "report_gate.py", "or (kept is not None and report == kept.raw)", ""),
    # The folders.
    ("feedback-in-the-dot-folder", "common.py", 'FEEDBACK_FOLDER = "harness-feedback"', 'FEEDBACK_FOLDER = ".harness"'),
    # A READ path given by its end, and an exit code a command printed.
    ("read-end-not-looked-up", "report_gate.py", "            found = find_by_end(path, files)\n", "            found = []\n"),
    ("read-end-shared-taken", "report_gate.py", "if len(found) > 1:", "if False:"),
    ("read-end-line-unchecked", "report_gate.py", "            full = os.path.join(root, found[0])\n", "            continue\n"),
    ("printed-exit-ignored", "report_gate.py", "if code not in seen and not re.search(PRINTED_EXIT.format(code=code), printed, re.I)", "if code not in seen"),
    ("printed-exit-any-number", "report_gate.py", "returned|error)", "returned|error|)"),
    ("printed-exit-no-make-error", "report_gate.py", "returned|error)", "returned)"),
    ("send-back-no-example", "report_gate.py", "A Runs: line naming the fixture would have helped.", "Name the fix."),
    # The report is judged before the handback, while the agent can still fix it.
    ("handback-mode-ignored", "report_gate.py", 'if sys.argv[1:2] == ["handback"]:', "if False:"),
    ("handback-never-refused", "report_gate.py", "    print(make_send_back(problems, is_handback=True), file=sys.stderr)\n\n    return 2", "    print(make_send_back(problems, is_handback=True), file=sys.stderr)\n\n    return 0"),
    ("handback-not-counted", "report_gate.py", "    write_atomic(get_send_backs_path(event), str(tries + 1))\n    print(make_send_back(problems, is_handback=True)", "    print(make_send_back(problems, is_handback=True)"),
    ("handback-no-cap", "report_gate.py", "or not is_judged(root, event) or tries >= MAX_SEND_BACKS:", "or not is_judged(root, event):"),
    ("handback-asks-for-sections", "report_gate.py", "print(make_send_back(problems, is_handback=True), file=sys.stderr)", "print(make_send_back(problems), file=sys.stderr)"),
    ("handback-claims-unread", "report_gate.py", 'judged = {**event, "agent_transcript_path": str(path)} if path is not None else event', "judged = event"),
    ("handback-judges-every-agent", "report_gate.py", "or not is_judged(root, event) or tries", "or tries"),
    # The app's notices of a finished agent, and the Agents section of the status.
    ("notice-attachment-unread", "turn.py", 'if line.get("type") == "attachment" and isinstance(attachment, dict) and isinstance(attachment.get("prompt"), str):', "if False:"),
    ("notice-queue-unread", "turn.py", 'if line.get("type") == "queue-operation" and isinstance(line.get("content"), str):', "if False:"),
    ("agents-not-checked", "turn.py", "        if not is_deferred:\n            problems += check_agents(message, call_lines)\n", ""),
    ("agents-anywhere-counts", "turn.py", 'section = " ".join(get_agents_section(message).lower().split())', 'section = " ".join(message.lower().split())'),
    ("agents-case-matters", "turn.py", "missing = [name for name in names if name.lower() not in section]", "missing = [name for name in names if name not in section]"),
    ("agents-description-dropped", "turn.py", "if name in AGENT_TOOLS and isinstance(description, str) and description.strip():", "if False:"),
    ("agents-description-not-joined", "turn.py", "' '.join(description.split())", "description"),
    ("context-tmp-said-refused", "context.py", "A write under `/tmp` runs, with a note", "A write under `/tmp` is refused"),
)


class MutantRun(NamedTuple):
    """One mutant's name, the exit code of the cases run on it, and the cases that failed."""

    name: str
    code: int
    failed: list[str]


def run_mutant(name: str, script: str, old: str, new: str, /) -> MutantRun:
    """Breaks a copy of the hooks and runs the cases on it; returns the name, the exit code and the failed cases."""

    folder = WORK / name
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree(HOOKS, folder, ignore=shutil.ignore_patterns("__pycache__"))
    path = folder / script
    path.write_text(path.read_text().replace(old, new))
    command = ["uv", "run", "python", str(RUN_CASES), "--hooks", str(folder), "--fail-fast", "--first", script, "--threads", str(CASE_THREADS)]
    try:
        run = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return MutantRun(name, TIMED_OUT, [])
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    failed = [line[5:].split(":")[0] for line in run.stdout.splitlines() if line.startswith("FAIL")]

    return MutantRun(name, run.returncode, failed)


def get_rotted_names() -> list[str]:
    """The mutants that would prove nothing: their text to break is gone or occurs twice, the broken hook no longer
    parses (every case would fail for that reason alone), or another mutant makes the same change."""

    rotted = []
    seen = set()
    for name, script, old, new in MUTANTS:
        text = (HOOKS / script).read_text()
        try:
            ast.parse(text.replace(old, new))
            parses = True
        except SyntaxError:
            parses = False
        if text.count(old) != 1 or not parses or (script, old, new) in seen:
            rotted.append(name)
        seen.add((script, old, new))

    return rotted


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
    timeouts = 0
    os.nice(LOW_PRIORITY)
    with ThreadPoolExecutor(arguments.jobs) as pool:
        futures = [pool.submit(run_mutant, *mutant) for mutant in chosen]
        for future in as_completed(futures):
            name, code, failed = future.result()
            survivors += code == 0
            timeouts += code == TIMED_OUT
            verdict = "SURVIVED" if code == 0 else "TIMED OUT" if code == TIMED_OUT else f"killed by {len(failed)}"
            print(f"{verdict:16} {name}: {failed[:2]}", flush=True)
    print(f"{len(chosen)} mutants, {survivors} survived, {timeouts} timed out")
    if WORK.exists() and not any(WORK.iterdir()):
        WORK.rmdir()

    return 1 if survivors or timeouts else 0


if __name__ == "__main__":
    sys.exit(main())

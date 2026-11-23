#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import argparse
import ast
import codecs
import io
import json
import os
import re
import subprocess
import sys
import tokenize
import tomllib
from collections import Counter
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import NamedTuple

from common import find_project

RULES = ("comment", "docstring", "split", "untyped", "tensor", "tolerance")
MAX_LINES = 10
GIT_TIMEOUT_SECONDS = 5
TOLERANCE_FUNCTIONS = frozenset({"assert_close", "allclose", "isclose"})
TOLERANCE_KEYWORDS = frozenset({"rtol", "atol"})
STANDARD_LIBRARY_MATH_MODULES = frozenset({"math", "cmath"})
POSITIONAL_TOLERANCE_COUNTS = {"allclose": 4, "isclose": 4}
SKIPPED_FOLDERS = frozenset({".venv", "node_modules", "site-packages"})
DIRECTIVE = re.compile(r"(?:type:\s*ignore(?:\[[^\]]*\])?|noqa(?::\s*[A-Za-z]+\d+(?:\s*,\s*[A-Za-z]+\d+)*)?|pyright:\s*(?:ignore|basic|strict|standard)\b.*|ruff:\s*(?:noqa|isort:\s*\w+).*|fmt:\s*(?:off|on|skip)|pragma:\s*no (?:cover|branch).*|mypy:\s*(?:ignore\S*|strict|(?:dis|en)able-error-code.*|[a-z_-]+\s*=.*)|pylint:\s*(?:disable|enable)\b.*|isort:\s*\w+|ty:\s*ignore(?:\[[^\]]*\])?)\s*(?:#.*)?")
LICENSE_WORDS = ("license", "copyright", "spdx")
ENCODING_LINE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")
SCRIPT_BLOCK_START = re.compile(r"^# /// [A-Za-z0-9-]+$")
SCRIPT_BLOCK_END = "# ///"
DOCSTRING_SELECTION = re.compile(r"D\d*")
RUFF_FILES = (".ruff.toml", "ruff.toml")
UNFORMATTED_LINE_LENGTH = 320
HEADER_SKIPPED_FIELDS = frozenset({"body", "orelse", "finalbody", "handlers", "cases", "decorator_list", "type_comment"})
CHANGES = {
    "comment": "delete the comment; put the meaning in a name or a named intermediate",
    "docstring": "delete the docstring; the name says what it does",
    "split": "join it onto one line; name an intermediate if it is hard to read",
    "tensor": "annotate the tensor with a jaxtyping dtype and axes",
    "tolerance": "default tolerances; pass rtol and atol measured from the dtype",
}


class Finding(NamedTuple):

    rule: str
    line: int
    source: str
    change: str


class Style(NamedTuple):

    is_layout_owned: bool
    is_docstring_demanded: bool


class Scan(NamedTuple):

    comments: list[tuple[int, str]]
    interior_lines: frozenset[int]
    first_code_line: int


def read_toml(path: Path, /) -> dict:

    try:
        return tomllib.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def read_ruff_config(root: Path, /) -> dict | None:

    for name in RUFF_FILES:
        if (root / name).is_file():
            return read_toml(root / name)
    ruff = read_toml(root / "pyproject.toml").get("tool", {}).get("ruff")

    return ruff if isinstance(ruff, dict) else None


def get_ruff_selections(ruff: dict, /) -> list[str]:

    lint = ruff.get("lint") if isinstance(ruff.get("lint"), dict) else {}
    selections: list[str] = []
    for table in (ruff, lint):
        for key in ("select", "extend-select"):
            value = table.get(key)
            selections += [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    return selections


def is_unformatted_ruff(ruff: dict, /) -> bool:

    format_table = ruff.get("format") if isinstance(ruff.get("format"), dict) else {}
    length = ruff.get("line-length")
    is_long = isinstance(length, int) and length >= UNFORMATTED_LINE_LENGTH

    return is_long and format_table.get("skip-magic-trailing-comma") is True


def get_style(root: Path, /) -> Style:

    ruff = read_ruff_config(root)
    has_black = "black" in read_toml(root / "pyproject.toml").get("tool", {})
    is_layout_owned = has_black or (ruff is not None and not is_unformatted_ruff(ruff))
    selections = get_ruff_selections(ruff) if ruff is not None else []

    return Style(is_layout_owned, any(DOCSTRING_SELECTION.fullmatch(item) for item in selections))


def split_lines(text: str, /) -> list[str]:

    return [line.rstrip("\r") for line in text.split("\n")]


def read_source(path: Path, /) -> str:

    return path.read_text(errors="replace")


def is_encoding_line(string: str, /) -> bool:

    match = ENCODING_LINE.match(string)
    try:
        return match is not None and bool(codecs.lookup(match.group(1)))
    except LookupError:
        return False


def scan_tokens(text: str, /) -> Scan:

    comments: list[tuple[int, str]] = []
    interior: set[int] = set()
    first_code_line = 0
    depth = 0
    start_line = 0
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            comments.append((token.start[0], token.string))
        elif token.type not in (tokenize.NL, tokenize.ENCODING) and not first_code_line:
            first_code_line = token.start[0]
        if token.type == tokenize.FSTRING_START:
            depth += 1
            start_line = token.start[0] if depth == 1 else start_line
        elif token.type == tokenize.FSTRING_END:
            depth -= 1
            if depth == 0:
                interior.update(range(start_line + 1, token.end[0] + 1))
        elif token.type == tokenize.STRING and depth == 0:
            interior.update(range(token.start[0] + 1, token.end[0] + 1))

    return Scan(comments, frozenset(interior), first_code_line or len(split_lines(text)) + 1)


def get_script_block_lines(lines: list[str], /) -> set[int]:

    inside: set[int] = set()
    start = 0
    for number, line in enumerate(lines, 1):
        if not start and SCRIPT_BLOCK_START.match(line):
            start = number
        if start:
            inside.add(number)
        if start and number > start and line.rstrip() == SCRIPT_BLOCK_END:
            start = 0

    return inside


def get_license_lines(scan: Scan, /) -> set[int]:

    header = [(line, string) for line, string in scan.comments if line < scan.first_code_line]
    blocks: list[list[tuple[int, str]]] = []
    for comment in header:
        if blocks and blocks[-1][-1][0] + 1 == comment[0]:
            blocks[-1].append(comment)
        else:
            blocks.append([comment])

    return {line for block in blocks if any(word in " ".join(string for _, string in block).lower() for word in LICENSE_WORDS) for line, _ in block}


def find_comments(text: str, scan: Scan, /) -> Iterator[tuple[str, int, str]]:

    script_lines = get_script_block_lines(split_lines(text))
    license_lines = get_license_lines(scan)
    for line, string in scan.comments:
        body = string.lstrip("#").strip()
        is_shebang = line == 1 and string.startswith("#!")
        is_encoding = line <= 2 and is_encoding_line(string)
        is_directive = DIRECTIVE.fullmatch(body) is not None
        if not (is_shebang or is_encoding or is_directive or line in script_lines or line in license_lines):
            yield "comment", line, CHANGES["comment"]


def find_docstrings(tree: ast.Module, /) -> Iterator[tuple[str, int, str]]:

    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and ast.get_docstring(node, clean=False) is not None:
            yield "docstring", node.body[0].lineno, CHANGES["docstring"]


def get_header_end_line(node: ast.AST, /) -> int:

    children = [child for field, value in ast.iter_fields(node) if field not in HEADER_SKIPPED_FIELDS for child in (value if isinstance(value, list) else [value]) if isinstance(child, ast.AST)]
    end_lines = [part.end_lineno for child in children for part in ast.walk(child) if getattr(part, "end_lineno", None)]

    return max([node.lineno, *end_lines])


def count_code_lines(first: int, last: int, interior: frozenset[int], /) -> int:

    return len([line for line in range(first, last + 1) if line not in interior])


def get_element_spans(value: ast.expr, /) -> list[tuple[int, int]]:

    if isinstance(value, ast.Dict):
        return [((key or entry).lineno, entry.end_lineno or entry.lineno) for key, entry in zip(value.keys, value.values)]
    elements = value.elts if isinstance(value, ast.List | ast.Tuple | ast.Set) else []

    return [(element.lineno, element.end_lineno or element.lineno) for element in elements]


def is_table(node: ast.AST, /) -> bool:

    value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
    if not isinstance(value, ast.List | ast.Tuple | ast.Set | ast.Dict) or node.lineno != value.lineno:
        return False
    spans = get_element_spans(value)
    is_each_on_one_line = all(first == last for first, last in spans)
    lines = [first for first, _ in spans]

    return bool(spans) and is_each_on_one_line and lines[0] > value.lineno and lines == sorted(set(lines))


def find_split_statements(tree: ast.Module, interior: frozenset[int], /) -> Iterator[tuple[str, int, str]]:

    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt | ast.ExceptHandler):
            continue
        has_header = hasattr(node, "body") or isinstance(node, ast.Match)
        last = get_header_end_line(node) if has_header else node.end_lineno or node.lineno
        if count_code_lines(node.lineno, last, interior) > 1 and not is_table(node):
            yield "split", node.lineno, CHANGES["split"]
        for decorator in getattr(node, "decorator_list", []):
            if count_code_lines(decorator.lineno, decorator.end_lineno or decorator.lineno, interior) > 1:
                yield "split", decorator.lineno, CHANGES["split"]


def get_unannotated_names(node: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool, /) -> list[str]:

    arguments = node.args
    positional = [*arguments.posonlyargs, *arguments.args]
    skipped = positional[:1] if is_method and positional and positional[0].arg in ("self", "cls") else []
    every = [*positional, *([arguments.vararg] if arguments.vararg else []), *arguments.kwonlyargs, *([arguments.kwarg] if arguments.kwarg else [])]
    names = [argument.arg for argument in every if argument.annotation is None and argument not in skipped]

    return names if node.returns is not None else [*names, "the return type"]


def find_untyped(tree: ast.Module, /) -> Iterator[tuple[str, int, str]]:

    methods = {id(item) for node in ast.walk(tree) if isinstance(node, ast.ClassDef) for item in node.body}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names = get_unannotated_names(node, id(node) in methods)
            if names:
                yield "untyped", node.lineno, f"annotate {', '.join(names)}"


def imports_jaxtyping(tree: ast.Module, /) -> bool:

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.module.split(".")[0] == "jaxtyping":
            return True
        if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "jaxtyping" for alias in node.names):
            return True

    return False


def is_bare_tensor(annotation: ast.expr, /) -> bool:

    if isinstance(annotation, ast.Name):
        return annotation.id == "Tensor"
    if isinstance(annotation, ast.Attribute):
        return annotation.attr == "Tensor" and isinstance(annotation.value, ast.Name) and annotation.value.id == "torch"
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return is_bare_tensor(annotation.left) or is_bare_tensor(annotation.right)

    return False


def find_bare_tensors(tree: ast.Module, /) -> Iterator[tuple[str, int, str]]:

    if not imports_jaxtyping(tree):
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            arguments = node.args
            every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *([arguments.vararg] if arguments.vararg else []), *([arguments.kwarg] if arguments.kwarg else [])]
            annotations = [argument.annotation for argument in every if argument.annotation is not None]
            if node.returns is not None:
                annotations.append(node.returns)
            for annotation in annotations:
                if is_bare_tensor(annotation):
                    yield "tensor", annotation.lineno, CHANGES["tensor"]


def has_explicit_tolerances(call: ast.Call, name: str, is_torch_function: bool, /) -> bool:

    if any(keyword.arg is None for keyword in call.keywords):
        return True
    given = {keyword.arg for keyword in call.keywords}
    if TOLERANCE_KEYWORDS <= given:
        return True
    needed = POSITIONAL_TOLERANCE_COUNTS.get(name)
    if needed is None:
        return False

    return len(call.args) >= (needed if is_torch_function else needed - 1)


def find_default_tolerances(tree: ast.Module, /) -> Iterator[tuple[str, int, str]]:

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute) and function.attr in TOLERANCE_FUNCTIONS:
            if isinstance(function.value, ast.Name) and function.value.id in STANDARD_LIBRARY_MATH_MODULES:
                continue
            name = function.attr
            is_torch_function = isinstance(function.value, ast.Name) and function.value.id == "torch"
        elif isinstance(function, ast.Name) and function.id == "assert_close":
            name = function.id
            is_torch_function = False
        else:
            continue
        if not has_explicit_tolerances(node, name, is_torch_function):
            yield "tolerance", node.lineno, CHANGES["tolerance"]


def find_findings(text: str, style: Style, rules: Sequence[str], /) -> list[Finding] | None:

    try:
        tree = ast.parse(text)
        scan = scan_tokens(text)
    except (SyntaxError, ValueError, tokenize.TokenError):
        return None
    wanted = {rule for rule in rules if not (rule == "split" and style.is_layout_owned) and not (rule == "docstring" and style.is_docstring_demanded)}
    raw = [
        *(find_comments(text, scan) if "comment" in wanted else ()),
        *(find_docstrings(tree) if "docstring" in wanted else ()),
        *(find_split_statements(tree, scan.interior_lines) if "split" in wanted else ()),
        *(find_untyped(tree) if "untyped" in wanted else ()),
        *(find_bare_tensors(tree) if "tensor" in wanted else ()),
        *(find_default_tolerances(tree) if "tolerance" in wanted else ()),
    ]
    lines = split_lines(text)

    return sorted((Finding(rule, line, lines[line - 1].strip(), change) for rule, line, change in raw), key=lambda finding: (finding.line, finding.rule))


def find_new_findings(text: str, head_text: str | None, root: Path, rules: Sequence[str], /) -> list[Finding]:

    style = get_style(root)
    found = find_findings(text, style, rules)
    if found is None:
        return []
    if head_text is None:
        return found
    baseline = find_findings(head_text, style, rules)
    if baseline is None:
        return []
    allowed = Counter((finding.rule, finding.source) for finding in baseline)
    seen: Counter[tuple[str, str]] = Counter()
    new: list[Finding] = []
    for finding in found:
        identity = (finding.rule, finding.source)
        seen[identity] += 1
        if seen[identity] > allowed[identity]:
            new.append(finding)

    return new


def read_head_text(path: Path, /) -> str | None:

    try:
        run = subprocess.run(["git", "show", f"HEAD:./{path.name}"], cwd=path.parent, capture_output=True, text=True, errors="replace", timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None

    return run.stdout if run.returncode == 0 else None


def is_in_scope(path: Path, root: Path, /) -> bool:

    return path.suffix == ".py" and root in path.parents and not SKIPPED_FOLDERS.intersection(path.relative_to(root).parts)


def get_rules(config: dict, /) -> list[str]:

    rules = config.get("lint", {}).get("rules")

    return [rule for rule in rules if rule in RULES] if isinstance(rules, list) else []


def make_note(findings: list[Finding], name: str, /) -> str:

    lines = [f"{name}:{finding.line}: {finding.rule}: {finding.change}" for finding in findings[:MAX_LINES]]
    if len(findings) > MAX_LINES:
        lines.append(f"and {len(findings) - MAX_LINES} more")

    return "New lint findings in the file you just wrote (fix these in the unit's final batch, together with the rest, and do not rerun the linter after each edit):\n" + "\n".join(lines)


def main() -> int:
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input") or {}
    given = tool_input.get("file_path")
    if event.get("tool_name") not in ("Edit", "Write") or not isinstance(given, str) or not given:
        return 0
    cwd = event.get("cwd") or os.getcwd()
    root, config = find_project(cwd)
    rules = get_rules(config)
    path = (Path(cwd) / given).resolve()
    if not rules or not is_in_scope(path, root):
        return 0
    findings = find_new_findings(read_source(path), read_head_text(path), root, rules)
    if findings:
        note = make_note(findings, str(path.relative_to(root)))
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}}))

    return 0


def run_git_lines(arguments: list[str], cwd: Path, /) -> list[str]:

    try:
        run = subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True, errors="replace", timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return []

    return [name for name in run.stdout.split("\0") if name] if run.returncode == 0 else []


def get_changed_python_files(cwd: Path, /) -> list[Path]:

    unstaged = run_git_lines(["ls-files", "-z", "--modified", "--others", "--exclude-standard"], cwd)
    staged = run_git_lines(["diff", "--cached", "-z", "--name-only", "--relative", "--diff-filter=ACMR"], cwd)
    candidates = [(cwd / name).resolve() for name in dict.fromkeys([*unstaged, *staged])]

    return [path for path in candidates if path.suffix == ".py" and path.is_file()]


def expand_paths(names: list[str], cwd: Path, /) -> list[Path]:

    paths = [(cwd / name).resolve() for name in names]
    files = [file for path in paths for file in (sorted(path.rglob("*.py")) if path.is_dir() else [path])]

    return list(dict.fromkeys(file for file in files if file.is_file()))


def run_cli(arguments: list[str], /) -> int:

    parser = argparse.ArgumentParser(prog="harness-lint", description="Print the Python lint findings of the harness: the new ones against HEAD, or every one with --all.")
    parser.add_argument("--all", action="store_true", help="print every finding, not only the new ones")
    parser.add_argument("paths", nargs="*", help="files or folders; default: the changed and untracked .py files")
    parsed = parser.parse_args(arguments)
    cwd = Path.cwd()
    root, config = find_project(str(cwd))
    rules = get_rules(config)
    files = expand_paths(parsed.paths, cwd) if parsed.paths else get_changed_python_files(cwd)
    style = get_style(root)
    num_printed = 0
    for path in files:
        if not rules or not is_in_scope(path, root):
            continue
        text = read_source(path)
        findings = find_findings(text, style, rules) or [] if parsed.all else find_new_findings(text, read_head_text(path), root, rules)
        for finding in findings:
            print(f"{path.relative_to(root)}:{finding.line}: {finding.rule}: {finding.change}")
            num_printed += 1

    return 1 if num_printed else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--cli"]:
        sys.exit(run_cli(sys.argv[2:]))
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness lint hook failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)

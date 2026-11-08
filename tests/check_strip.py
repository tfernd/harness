#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
from __future__ import annotations

import ast
import collections
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = Path(os.environ.get("STRIP_COMMENTS_TOOL", ROOT / "bin" / "strip-comments"))
HOOK = ROOT / ".githooks" / "pre-commit"
WORK = ROOT / "__scratch__" / "strip"
SHELL_SHEBANG = re.compile(r"^#!\s*\S*/(?:env\s+)?(?:-\S+\s+)*(?:ba|z)?sh\b")
PEP723_BLOCK = re.compile(r"^# /// script$.*?^# ///$", re.DOTALL | re.MULTILINE)
CODING_LINE = re.compile(r"coding[:=]\s*[-\w.]+")

Failures = list[str]


class Outcome:
    def __init__(self, code: int, out: str, err: str) -> None:
        self.code = code
        self.out = out
        self.err = err


def run_tool(*arguments: str, stdin: str | None = None) -> Outcome:
    done = subprocess.run(
        [sys.executable, str(TOOL), *arguments], input=stdin, capture_output=True, text=True, cwd=WORK
    )
    return Outcome(done.returncode, done.stdout, done.stderr)


def strip_via_stdin(name: str, source: str) -> Outcome:
    return run_tool("--stdin", name, stdin=source)


def kind_of_tracked(path: Path) -> str | None:
    name = path.name
    if name.endswith((".html", ".html.in")):
        return "html"
    suffix_kinds = {".py": "python", ".sh": "shell", ".js": "js", ".css": "css"}
    if path.suffix in suffix_kinds:
        return suffix_kinds[path.suffix]
    if not path.suffix and SHELL_SHEBANG.match(path.read_text().split("\n", 1)[0]):
        return "shell"
    return None


def list_candidate_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, cwd=ROOT, check=True
    ).stdout.splitlines()
    found = [ROOT / name for name in listed if (ROOT / name).is_file()]
    return [path for path in found if kind_of_tracked(path)]


def protected_rows(source: str) -> set[int]:
    rows: set[int] = set()
    lines = source.split("\n")
    if lines[0].startswith("#!"):
        rows.add(1)
    for row in (1, 2):
        if row <= len(lines) and lines[row - 1].lstrip().startswith("#") and CODING_LINE.search(lines[row - 1]):
            rows.add(row)
    for block in PEP723_BLOCK.finditer(source):
        first = source.count("\n", 0, block.start()) + 1
        rows.update(range(first, first + block.group().count("\n") + 1))
    return rows


def string_tokens(source: str) -> collections.Counter[str]:
    strings = (tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", tokenize.STRING))
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return collections.Counter(token.string for token in tokens if token.type in strings)


def docstring_nodes(tree: ast.AST) -> list[ast.Expr]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.append(first)
    return found


def dump_without_docstrings(tree: ast.Module) -> str:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = node.body[1:] or [ast.Expr(ast.Constant(Ellipsis))]
    return ast.dump(tree)


def docstring_token_strings(source: str, tree: ast.Module) -> collections.Counter[str]:
    lines = source.split("\n")
    starts = {(node.lineno, len(lines[node.lineno - 1].encode()[: node.col_offset].decode())) for node in docstring_nodes(tree)}
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return collections.Counter(token.string for token in tokens if token.type == tokenize.STRING and token.start in starts)


def check_python(original: str, result: str) -> Failures:
    failures: Failures = []
    tree = ast.parse(original)
    result_tree = ast.parse(result)
    allowed = protected_rows(result)
    for token in tokenize.generate_tokens(io.StringIO(result).readline):
        if token.type == tokenize.COMMENT and token.start[0] not in allowed:
            failures.append(f"comment left at line {token.start[0]}")
    if docstring_nodes(result_tree):
        failures.append("docstring left")
    missing = string_tokens(original) - docstring_token_strings(original, tree) - string_tokens(result)
    if missing:
        failures.append(f"string literals lost: {list(missing)[:3]}")
    if dump_without_docstrings(tree) != dump_without_docstrings(result_tree):
        failures.append("syntax tree changed beyond docstrings")
    kept_blocks = PEP723_BLOCK.findall(original)
    if kept_blocks != PEP723_BLOCK.findall(result):
        failures.append("PEP 723 block changed")
    return failures


def check_syntax_with_real_parser(kind: str, result: str, folder: Path) -> Failures:
    match kind:
        case "python":
            target = folder / "result.py"
            target.write_text(result)
            done = subprocess.run([sys.executable, "-m", "py_compile", str(target)], capture_output=True, text=True)
        case "shell":
            done = subprocess.run(["bash", "-n"], input=result, capture_output=True, text=True)
        case "js":
            target = folder / "result.mjs"
            target.write_text(result)
            done = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
        case _:
            done = run_tool("--syntax", "--stdin", "x.css" if kind == "css" else "x.html", stdin=result)
            return [f"balance: {done.out.strip()}"] if done.code else []
    return [f"does not parse: {done.stderr.strip()[-200:]}"] if done.returncode else []


def check_file(path: Path, folder: Path) -> tuple[Failures, bool]:
    kind = kind_of_tracked(path)
    original = path.read_text()
    copy = folder / path.name
    copy.write_text(original)
    done = run_tool(str(copy))
    if done.code == 2 and "__doc__" in original:
        return [], True
    if done.code:
        return [f"exit {done.code}: {done.err.strip()}"], False
    result = copy.read_text()
    failures: Failures = []
    failures += check_syntax_with_real_parser(kind, result, folder)
    if kind == "python":
        failures += check_python(original, result)
    again = strip_via_stdin(path.name, result)
    if again.code or again.out != result:
        failures.append("stripping a second time changes the result")
    if run_tool("--check", str(copy)).code:
        failures.append("--check still finds a comment in the result")
    if (run_tool("--check", str(path)).code == 1) != (result != original):
        failures.append("--check disagrees with the rewrite about the original")
    return failures, False


PYTHON_SOURCE = '''#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Module doc."""
# comment
x = "# not"  # trailing
y = f"{x} # {x!r}"  # c

def f():
    """Only doc."""


class A:
    """Doc."""
    # c
    def g(self):
        """Doc."""
        return 1  # t
'''
PYTHON_EXPECTED = '''#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
x = "# not"
y = f"{x} # {x!r}"

def f():
    ...


class A:
    def g(self):
        return 1
'''
SHELL_SOURCE = """#!/usr/bin/env bash
# header
set -eu
arr=(a b)
echo ${#arr[@]} $# "$#" ${#} # gone
echo a#b "a # b" 'c # d' $'e # \\' f'  # gone
cat <<'EOF'
# kept in heredoc
$#
EOF
cat <<-EOT
\t# kept too
\tEOT
echo "$(echo x # c
)"
x=$((1 << 2)) # c
"""
SHELL_EXPECTED = """#!/usr/bin/env bash
set -eu
arr=(a b)
echo ${#arr[@]} $# "$#" ${#}
echo a#b "a # b" 'c # d' $'e # \\' f'
cat <<'EOF'
# kept in heredoc
$#
EOF
cat <<-EOT
\t# kept too
\tEOT
echo "$(echo x
)"
x=$((1 << 2))
"""
JS_SOURCE = """// header
const url = "http://x.com/a"; // gone
const re = /\\/\\/ [/]x/g; // gone
const q = a / b / c; // div
const t = `a ${ b + `c // ${d}` } // e`; // gone
/* block
   more */
const s = 1; /* mid */ const u = 2;
function f() { return /ab+c/.test(x); }
"""
JS_EXPECTED = """const url = "http://x.com/a";
const re = /\\/\\/ [/]x/g;
const q = a / b / c;
const t = `a ${ b + `c // ${d}` } // e`;
const s = 1; const u = 2;
function f() { return /ab+c/.test(x); }
"""
CSS_SOURCE = """/* header */
a { content: "/* x */"; /* gone */ color: red; }
/* multi
line */
b::after { content: '\\'/*'; }
"""
CSS_EXPECTED = """a { content: "/* x */"; color: red; }
b::after { content: '\\'/*'; }
"""
HTML_SOURCE = """<!-- top -->
<p>text <!-- c --> more</p>
<style>
/* c */
a { color: red; }
</style>
<script>
// c
const u = "http://x"; /* c */
</script>
<script type="application/json">{"a": "// not"}</script>
"""
HTML_EXPECTED = """<p>text more</p>
<style>
a { color: red; }
</style>
<script>
const u = "http://x";
</script>
<script type="application/json">{"a": "// not"}</script>
"""
EXACT_CASES = (
    ("python", "case.py", PYTHON_SOURCE, PYTHON_EXPECTED),
    ("python: docstring on the def line", "case.py", 'def f(): """x"""\n', "def f(): ...\n"),
    ("python: encoding line kept", "case.py", "# -*- coding: utf-8 -*-\n# c\nx = 1\n", "# -*- coding: utf-8 -*-\nx = 1\n"),
    ("python: code lines not merged", "case.py", "x = (1,  # a\n     2)\n", "x = (1,\n     2)\n"),
    ("shell: bash script", "case.sh", SHELL_SOURCE, SHELL_EXPECTED),
    ("shell: extensionless with a shebang", "case", "#!/bin/sh\n# c\necho hi # c\n", "#!/bin/sh\necho hi\n"),
    ("js", "case.js", JS_SOURCE, JS_EXPECTED),
    ("css", "case.css", CSS_SOURCE, CSS_EXPECTED),
    ("html", "case.html", HTML_SOURCE, HTML_EXPECTED),
    ("html template", "case.html.in", HTML_SOURCE, HTML_EXPECTED),
    ("unknown extension is skipped", "case.md", "<!-- keep -->\n# keep\n", "<!-- keep -->\n# keep\n"),
)


def check_exact_cases() -> Failures:
    failures: Failures = []
    for label, name, source, expected in EXACT_CASES:
        done = strip_via_stdin(name, source)
        if done.out != expected:
            failures.append(f"{label}: got {done.out!r}")
        again = strip_via_stdin(name, done.out)
        if again.out != done.out:
            failures.append(f"{label}: second pass changes it")
        if run_tool("--check", "--stdin", name, stdin=source).code != (1 if source != expected else 0):
            failures.append(f"{label}: --check exit code")
    return failures


def check_doc_refusal() -> Failures:
    done = strip_via_stdin("reads_doc.py", "print(__doc__)\n")
    if done.code != 2 or "reads_doc.py" not in done.err:
        return [f"__doc__ reader not refused with exit 2 naming the file: {done.code} {done.err!r}"]
    return []


def check_cli_files(folder: Path) -> Failures:
    failures: Failures = []
    target = folder / "cli.py"
    target.write_text("x = 1  # c\n")
    clean = folder / "clean.py"
    clean.write_text("x = 1\n")
    done = run_tool("--check", str(clean), str(target))
    if done.code != 1 or str(target) not in done.out or str(clean) in done.out:
        failures.append(f"--check should list only the file with a comment: {done.code} {done.out!r}")
    if target.read_text() != "x = 1  # c\n":
        failures.append("--check wrote a file")
    if run_tool(str(target)).code or target.read_text() != "x = 1\n":
        failures.append("in-place rewrite failed")
    return failures


def check_hook(folder: Path) -> Failures:
    repo = folder / "hookrepo"
    (repo / "bin").mkdir(parents=True)
    (repo / ".githooks").mkdir()
    shutil.copy(TOOL, repo / "bin" / "strip-comments")
    shutil.copy(HOOK, repo / ".githooks" / "pre-commit")
    (repo / ".githooks" / "pre-commit").chmod(0o755)
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }

    def git(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *arguments], cwd=repo, env=environment, capture_output=True, text=True)

    git("init", "-q")
    git("config", "core.hooksPath", ".githooks")
    failures: Failures = []
    (repo / "a.py").write_text("x = 0\n")
    git("add", "a.py")
    git("commit", "-q", "-m", "base")
    (repo / "a.py").write_text("x = 1  # staged comment\n")
    git("add", "a.py")
    (repo / "a.py").write_text("x = 1  # staged comment\ny = 2  # unstaged comment\n")
    done = git("commit", "-q", "-m", "t")
    if done.returncode:
        return [f"hook refused a plain commit: {done.stderr.strip()}"]
    committed = git("show", "HEAD:a.py").stdout
    if committed != "x = 1\n":
        failures.append(f"committed blob not stripped: {committed!r}")
    if (repo / "a.py").read_text() != "x = 1\ny = 2\n":
        failures.append(f"working copy should keep its unstaged hunk without comments: {(repo / 'a.py').read_text()!r}")
    (repo / "b.py").write_text("print(__doc__)\n")
    git("add", "b.py")
    if git("commit", "-q", "-m", "u").returncode == 0:
        failures.append("hook let a file that reads __doc__ through")
    return failures


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(dir=WORK))
    failures: Failures = []
    refused = 0
    files = list_candidate_files()
    try:
        for path in files:
            problems, was_refused = check_file(path, folder)
            refused += was_refused
            failures += [f"{path.relative_to(ROOT)}: {problem}" for problem in problems]
        failures += [f"exact: {problem}" for problem in check_exact_cases()]
        failures += check_doc_refusal()
        failures += check_cli_files(folder)
        failures += check_hook(folder)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    for failure in failures:
        print(f"FAIL {failure}")
    print(f"{len(files)} files, {refused} refused for reading __doc__, {len(EXACT_CASES)} exact cases, {len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

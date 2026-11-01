"""The shell reader of the hooks: cuts a command into the simple commands it runs, as a shell reads it, word by word.

A heredoc's body, a quoted string, a `$((...))` and a `[[ ... ]]` hold no separator. What runs inside a word is read as
commands too: `$(...)`, backticks, `<(...)`, `>(...)`, and the substitutions in a `${...}`, a `$((...))` or the body of
an unquoted heredoc. A substitution is read by the same scanner as the text around it, so its closing parenthesis is
found past quotes, heredocs, comments and `case` arms.
"""

from __future__ import annotations

import re
from typing import NamedTuple

GLOB_CHARACTERS = "*?["
SEPARATORS = ";&|()\n"
# The operators a separator character starts, the longest first.
SEPARATOR_OPERATOR = re.compile(r";;&|;;|;&|&&|\|\||\|&|[;&|()\n]")
REDIRECT_OPERATOR = re.compile(r"<<<|<<-|<<|<>|<&|<|&>>|&>|>>|>&|>\||>")
PIPES = {"|", "|&"}
# The parameters whose second character is no glob and no comment (`$?`, `$*`, `$#`).
SPECIAL_PARAMETERS = "?*@#$!-"
# The keywords that open a loop. A sleep in a while or until loop waits for a result; one in a for loop waits a fixed
# count, so only the two polling keywords count as polling.
LOOP_KEYWORDS = {"for", "select", "until", "while"}
POLLING_LOOPS = {"until", "while"}
# The reserved words that may stand before a keyword in the same segment (`do while`, `then until`).
LEADING_WORDS = {"!", "{", "do", "elif", "else", "if", "then"}
# The words after which a `[[` or a `((` still starts a command.
OPENING_WORDS = LEADING_WORDS | POLLING_LOOPS


class Word(NamedTuple):
    """One shell word after quote removal, and whether it held an unquoted glob character."""

    text: str
    is_glob: bool


class Segment(NamedTuple):
    """One simple command: its words, its output redirect targets, whether a polling loop is open around it, whether
    it runs in a subshell (a group, a substitution, a pipeline or the background), where a `cd` does not persist."""

    words: list[Word]
    redirects: list[str]
    in_loop: bool
    in_group: bool


class Heredoc(NamedTuple):
    """A heredoc opened on the current line: its delimiter, whether `<<-` strips tabs, whether the delimiter is quoted,
    which leaves its body plain text."""

    delimiter: str
    is_dash: bool
    is_quoted: bool = False


def find_arithmetic_end(text: str, start: int, /) -> int:
    """The index after the `))` of the arithmetic opened just before `start`, or -1 when the two parentheses do not close
    together, which makes them nested subshells (`$((a) && (b))`) and no arithmetic."""

    depth = 2
    for index in range(start, len(text)):
        depth += {"(": 1, ")": -1}.get(text[index], 0)
        if depth == 1:
            return index + 2 if text[index + 1 : index + 2] == ")" else -1

    return -1


def find_backtick_end(text: str, start: int, /) -> int:
    """The index of the backtick that closes the one before `start`, or the end of the text."""

    index = start
    while index < len(text) and text[index] != "`":
        index += 2 if text[index] == "\\" else 1

    return min(index, len(text))


class Scanner:
    """Cuts a shell command into simple commands, reading quotes, substitutions, redirects and heredocs.

    A nested scanner reads the inside of a `$(`: it starts at `start` and stops at the parenthesis that closes it.
    """

    def __init__(
        self, text: str, open_loops: tuple[str, ...] = (), in_group: bool = False, start: int = 0, is_nested: bool = False, /
    ) -> None:
        self.text = text
        self.index = start
        self.is_nested = is_nested
        self.is_closed = False
        self.segments: list[Segment] = []
        self.in_group = in_group  # the text is a substitution, so its commands run in a subshell
        self.depth = 0  # the parenthesized groups open at the index
        self.case_depth = 0  # the `case` commands open at the index, whose arms hold an unmatched `)`
        self.in_pipeline = False  # a `|` was seen and the pipeline it belongs to has not ended
        self.list_start = 0  # the first segment of the list a `&` would send to the background
        self.words: list[Word] = []
        self.redirects: list[str] = []
        self.characters: list[str] = []
        self.is_word = False
        self.is_glob = False
        self.is_quoted = False
        self.target = ""  # "", "redirect", "duplicate", "heredoc" or "herestring": what the next word is
        self.heredocs: list[Heredoc] = []
        self.loops = list(open_loops)  # the loop keywords still open, the innermost last

    def end_word(self) -> None:
        if not self.is_word:
            return
        word = Word("".join(self.characters), self.is_glob)
        match self.target:
            case "redirect":
                self.redirects.append(word.text)
            case "duplicate":
                # A `>&` word that is a descriptor number or `-` names no file (`2>&1`, `>&-`).
                if not (word.text.isdigit() or word.text == "-"):
                    self.redirects.append(word.text)
            case "heredoc":
                self.heredocs[-1] = self.heredocs[-1]._replace(delimiter=word.text, is_quoted=self.is_quoted)
            case "herestring":
                pass  # the input of a command, not one of its words
            case _:
                self.track_keyword(word.text)
                self.words.append(word)
        self.characters, self.is_word, self.is_glob, self.is_quoted, self.target = [], False, False, False, ""

    def track_keyword(self, word: str, /) -> None:
        """Opens a loop or a `case` at the keyword that starts a command, and closes it at `done` or `esac`."""

        if any(earlier.text not in LEADING_WORDS for earlier in self.words):
            return
        if word in LOOP_KEYWORDS:
            self.loops.append(word)
        elif word == "done" and self.loops:
            self.loops.pop()
        elif word == "case":
            self.case_depth += 1
        elif word == "esac":
            self.case_depth = max(self.case_depth - 1, 0)

    def end_segment(self) -> bool:
        """Ends the simple command at the index; returns whether it held anything."""

        self.end_word()
        self.target = ""
        is_polling = any(loop in POLLING_LOOPS for loop in self.loops)
        has_command = bool(self.words or self.redirects)
        if has_command:
            is_grouped = self.in_group or self.depth > 0 or self.in_pipeline
            self.segments.append(Segment(self.words, self.redirects, is_polling, is_grouped))
        self.words, self.redirects = [], []

        return has_command

    def read_substitution(self, start: int, /) -> int:
        """Reads `$(...)`, `$((...))`, `<(...)` or a backtick string at `start`; returns the index after it."""

        text = self.text
        if text[start] == "`":
            end = find_backtick_end(text, start + 1)
            inner = re.sub(r"\\([`\\$])", r"\1", text[start + 1 : end])
            self.segments.extend(get_segments(inner, tuple(self.loops), True))
            return end + 1
        if text.startswith("$((", start):
            end = find_arithmetic_end(text, start + 3)
            if end >= 0:
                self.read_expansions(start + 3, end - 2)
                return end
        nested = Scanner(text, tuple(self.loops), True, start + 2, True)
        self.segments.extend(nested.scan())

        return nested.index + 1

    def read_expansions(self, start: int, end: int, /) -> None:
        """Reads the substitutions in text that is otherwise no command: an arithmetic or a heredoc's body."""

        index = start
        while index < end:
            if self.text[index] == "\\":
                index += 2
            elif self.text.startswith("$(", index) or self.text[index] == "`":
                index = self.read_substitution(index)
            else:
                index += 1

    def substitute(self, start: int, /) -> int:
        """Reads a substitution as a piece of the current word; returns the index after it."""

        end = self.read_substitution(start)
        self.characters.append("$")
        self.is_word = True

        return end

    def read_parameter(self, start: int, is_double_quoted: bool, /) -> int:
        """Reads a `${...}` as a piece of the current word, its substitutions as commands; returns the index after it."""

        text = self.text
        depth, index = 1, start + 2
        while index < len(text) and depth > 0:
            if text[index] == "\\":
                index += 2
            elif text[index] == "'" and not is_double_quoted:
                end = text.find("'", index + 1)
                index = len(text) if end < 0 else end + 1
            elif text.startswith("${", index):
                depth += 1
                index += 2
            elif text[index] == "}":
                depth -= 1
                index += 1
            elif text.startswith("$(", index) or text[index] == "`":
                index = self.read_substitution(index)
            else:
                index += 1
        self.characters.append("$")
        self.is_word = True

        return index

    def skip_heredocs(self) -> None:
        """Skips the bodies of the heredocs opened on the line just ended; an unquoted body still runs its substitutions."""

        for heredoc in self.heredocs:
            start = self.index
            body_end = len(self.text)
            while self.index < len(self.text):
                end = self.text.find("\n", self.index)
                end = len(self.text) if end < 0 else end
                line = self.text[self.index : end]
                line_start, self.index = self.index, end + 1
                if (line.lstrip("\t") if heredoc.is_dash else line) == heredoc.delimiter:
                    body_end = line_start
                    break
            if not heredoc.is_quoted:
                after = self.index
                self.read_expansions(start, body_end)
                self.index = after
        self.heredocs = []

    def read_double_quoted(self) -> None:
        text = self.text
        self.index += 1
        while self.index < len(text) and text[self.index] != '"':
            if text[self.index] == "\\" and self.index + 1 < len(text):
                self.characters.append(text[self.index + 1])
                self.index += 2
            elif text.startswith("$(", self.index) or text[self.index] == "`":
                self.index = self.substitute(self.index)
            elif text.startswith("${", self.index):
                self.index = self.read_parameter(self.index, True)
            else:
                self.characters.append(text[self.index])
                self.index += 1
        self.index += 1
        self.is_word = True
        self.is_quoted = True

    def read_redirect(self) -> None:
        text = self.text
        is_fd = self.characters and all(character.isdigit() for character in self.characters)
        if is_fd:
            self.characters, self.is_word = [], False
        else:
            self.end_word()
        match = REDIRECT_OPERATOR.match(text, self.index)
        operator = match.group() if match else text[self.index]
        self.index += len(operator)
        if operator.startswith("<<<"):
            self.target = "herestring"
        elif operator.startswith("<<"):
            self.heredocs.append(Heredoc("", operator.endswith("-")))
            self.target = "heredoc"
        elif ">" in operator:
            self.target = "duplicate" if operator == ">&" else "redirect"
        else:
            self.target = "herestring"

    def read_process_substitution(self) -> None:
        """Reads `<(...)` or `>(...)`; as a redirect's target it names no file (`> >(tee x)`)."""

        if self.target == "redirect":
            self.target = "herestring"
        self.index = self.substitute(self.index)

    def read_escape(self) -> None:
        """Reads a backslash and the character it escapes; a backslash before a newline joins the lines."""

        if self.text[self.index + 1 : self.index + 2] not in ("\n", ""):
            self.characters.append(self.text[self.index + 1])
            self.is_word = True
            self.is_quoted = True
        self.index += 2

    def read_single_quoted(self) -> None:
        end = self.text.find("'", self.index + 1)
        end = len(self.text) if end < 0 else end
        self.characters.append(self.text[self.index + 1 : end])
        self.is_word = True
        self.is_quoted = True
        self.index = end + 1

    def read_ansi_quoted(self) -> None:
        """Reads `$'...'`, where a backslash escapes a quote."""

        index = self.index + 2
        while index < len(self.text) and self.text[index] != "'":
            index += 2 if self.text[index] == "\\" else 1
        self.characters.append(self.text[self.index + 2 : index])
        self.is_word = True
        self.is_quoted = True
        self.index = index + 1

    def read_comment(self) -> None:
        end = self.text.find("\n", self.index)
        self.index = len(self.text) if end < 0 else end

    def read_separator(self, character: str, /) -> None:
        """Ends the simple command at a separator, tracks groups and pipelines, and skips the heredocs a newline starts."""

        has_command = self.end_segment()
        if character == ")" and self.is_nested and self.depth == 0 and self.case_depth == 0:
            self.is_closed = True
            return
        match = SEPARATOR_OPERATOR.match(self.text, self.index)
        operator = match.group() if match else character
        self.index += len(operator)
        if operator in PIPES:
            if has_command:
                self.segments[-1] = self.segments[-1]._replace(in_group=True)
            self.in_pipeline = True
        elif has_command or operator != "\n":
            self.in_pipeline = False
        if operator == "&":
            for index in range(self.list_start, len(self.segments)):
                self.segments[index] = self.segments[index]._replace(in_group=True)
        if operator in (";", "&", ";;", ";&", ";;&", "\n"):
            self.list_start = len(self.segments)
        if operator == "(":
            self.depth += 1
        elif operator == ")":
            self.depth = max(self.depth - 1, 0)
        if operator == "\n" and self.heredocs:
            self.skip_heredocs()

    def read_plain(self, character: str, /) -> None:
        self.characters.append(character)
        self.is_word = True
        self.is_glob = self.is_glob or character in GLOB_CHARACTERS
        self.index += 1

    def is_command_start(self) -> bool:
        """Whether a word at the index would be the command word of its segment."""

        return not self.is_word and all(word.text in OPENING_WORDS for word in self.words)

    def is_arithmetic_start(self) -> bool:
        """Whether a `((` at the index is a command or the head of a `for ((...))`."""

        return self.is_command_start() or (not self.is_word and [word.text for word in self.words] == ["for"])

    def read_test(self) -> None:
        """Reads `[[ ... ]]` as one unit: its operators separate nothing, and its patterns are no globs."""

        text = self.text
        self.words.append(Word("[[", False))
        self.index += 2
        while self.index < len(text):
            character = text[self.index]
            if character in " \t\r\n":
                self.end_word()
                self.index += 1
            elif text.startswith("]]", self.index) and not self.is_word:
                self.index += 2
                return
            elif character == "\\":
                self.read_escape()
            elif character == "'":
                self.read_single_quoted()
            elif character == '"':
                self.read_double_quoted()
            elif character in "$`":
                self.read_dollar()
            else:
                self.characters.append(character)
                self.is_word = True
                self.index += 1

    def read_dollar(self) -> None:
        """Reads what starts with a `$` or a backtick: a substitution, a parameter, an ANSI quote, or a plain `$`."""

        text, following = self.text, self.text[self.index + 1 : self.index + 2]
        if following == "(" or text[self.index] == "`":
            self.index = self.substitute(self.index)
        elif following == "{":
            self.index = self.read_parameter(self.index, False)
        elif following == "'":
            self.read_ansi_quoted()
        elif following and following in SPECIAL_PARAMETERS:
            self.characters.append(text[self.index : self.index + 2])
            self.is_word = True
            self.index += 2
        else:
            self.read_plain("$")

    def read_arithmetic_command(self) -> bool:
        """Reads a `(( ... ))` command or the head of a `for ((...))`; returns False when the parentheses are subshells."""

        end = find_arithmetic_end(self.text, self.index + 2)
        if end < 0:
            return False
        self.read_expansions(self.index + 2, end - 2)
        self.index = end

        return True

    def read_next(self) -> None:
        """Reads the token at the index: a quote, a substitution, a redirect, a separator, a blank or a plain character."""

        text, character = self.text, self.text[self.index]
        if character == "\\":
            self.read_escape()
        elif character == "'":
            self.read_single_quoted()
        elif character == '"':
            self.read_double_quoted()
        elif character in "$`":
            self.read_dollar()
        elif text.startswith(("<(", ">("), self.index):
            self.read_process_substitution()
        elif character in "<>" or (character == "&" and text[self.index + 1 : self.index + 2] == ">"):
            self.read_redirect()
        elif character == "#" and not self.is_word:
            self.read_comment()
        elif text.startswith("((", self.index) and self.is_arithmetic_start() and self.read_arithmetic_command():
            pass
        elif text.startswith("[[", self.index) and self.is_command_start() and text[self.index + 2 : self.index + 3].isspace():
            self.read_test()
        elif character in SEPARATORS:
            self.read_separator(character)
        elif character in " \t\r":
            self.end_word()
            self.index += 1
        else:
            self.read_plain(character)

    def scan(self) -> list[Segment]:
        while self.index < len(self.text) and not self.is_closed:
            self.read_next()
        self.end_segment()

        return self.segments


def get_segments(text: str, open_loops: tuple[str, ...] = (), in_group: bool = False, /) -> list[Segment]:
    """The simple commands of a shell command in the order they run, substitutions included.

    `open_loops` are the loops around the text; `in_group` says the text is itself a subshell.
    """

    return Scanner(text, open_loops, in_group).scan()

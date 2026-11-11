# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import re
from typing import NamedTuple

GLOB_CHARACTERS = "*?["
SEPARATORS = ";&|()\n"
SEPARATOR_OPERATOR = re.compile(r";;&|;;|;&|&&|\|\||\|&|[;&|()\n]")
REDIRECT_OPERATOR = re.compile(r"<<<|<<-|<<|<>|<&|<|&>>|&>|>>|>&|>\||>")
PIPES = frozenset({"|", "|&"})
SPECIAL_PARAMETERS = "?*@#$!-"
LOOP_KEYWORDS = frozenset({"for", "select", "until", "while"})
POLLING_LOOPS = frozenset({"until", "while"})
LEADING_WORDS = frozenset({"!", "{", "do", "elif", "else", "if", "then"})
OPENING_WORDS = LEADING_WORDS | POLLING_LOOPS
MAX_NESTING = 16


class Word(NamedTuple):

    text: str
    is_glob: bool


class Segment(NamedTuple):

    words: list[Word]
    redirects: list[str]
    in_loop: bool
    in_group: bool


class Heredoc(NamedTuple):

    delimiter: str
    is_dash: bool
    is_quoted: bool = False


def find_arithmetic_end(text: str, start: int, /) -> int:

    depth = 2
    for index in range(start, len(text)):
        depth += {"(": 1, ")": -1}.get(text[index], 0)
        if depth == 1:
            return index + 2 if text[index + 1 : index + 2] == ")" else -1

    return -1


def find_backtick_end(text: str, start: int, /) -> int:

    index = start
    while index < len(text) and text[index] != "`":
        index += 2 if text[index] == "\\" else 1

    return min(index, len(text))


class Scanner:

    def __init__(
        self, text: str, /, *, open_loops: tuple[str, ...] = (), in_group: bool = False, start: int = 0, is_nested: bool = False, nesting: int = 0
    ) -> None:
        self.text = text
        self.nesting = nesting
        self.index = start
        self.is_nested = is_nested
        self.is_closed = False
        self.segments: list[Segment] = []
        self.in_group = in_group
        self.depth = 0
        self.case_depth = 0
        self.in_pipeline = False
        self.list_start = 0
        self.words: list[Word] = []
        self.redirects: list[str] = []
        self.characters: list[str] = []
        self.is_word = False
        self.is_glob = False
        self.is_quoted = False
        self.target = ""
        self.heredocs: list[Heredoc] = []
        self.loops = list(open_loops)

    def end_word(self) -> None:
        if not self.is_word:
            return
        word = Word("".join(self.characters), self.is_glob)
        match self.target:
            case "redirect":
                self.redirects.append(word.text)
            case "duplicate":
                if not (word.text.isdigit() or word.text == "-"):
                    self.redirects.append(word.text)
            case "heredoc":
                self.heredocs[-1] = self.heredocs[-1]._replace(delimiter=word.text, is_quoted=self.is_quoted)
            case "herestring":
                pass
            case _:
                self.track_keyword(word.text)
                self.words.append(word)
        self.characters, self.is_word, self.is_glob, self.is_quoted, self.target = [], False, False, False, ""

    def track_keyword(self, word: str, /) -> None:

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

        text = self.text
        if self.nesting >= MAX_NESTING:
            return start + (1 if text[start] == "`" else 2)
        if text[start] == "`":
            end = find_backtick_end(text, start + 1)
            inner = re.sub(r"\\([`\\$])", r"\1", text[start + 1 : end])
            self.segments.extend(get_segments(inner, open_loops=tuple(self.loops), in_group=True, nesting=self.nesting + 1))
            return end + 1
        if text.startswith("$((", start):
            end = find_arithmetic_end(text, start + 3)
            if end >= 0:
                self.read_expansions(start + 3, end - 2)
                return end
        nested = Scanner(text, open_loops=tuple(self.loops), in_group=True, start=start + 2, is_nested=True, nesting=self.nesting + 1)
        self.segments.extend(nested.scan())

        return nested.index + 1

    def read_expansions(self, start: int, end: int, /) -> None:

        index = start
        while index < end:
            if self.text[index] == "\\":
                index += 2
            elif self.text.startswith("$(", index) or self.text[index] == "`":
                index = self.read_substitution(index)
            else:
                index += 1

    def substitute(self, start: int, /) -> int:

        end = self.read_substitution(start)
        self.characters.append("$")
        self.is_word = True

        return end

    def read_parameter(self, start: int, is_double_quoted: bool, /) -> int:

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

        if self.target == "redirect":
            self.target = "herestring"
        self.index = self.substitute(self.index)

    def read_escape(self) -> None:

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

        return not self.is_word and all(word.text in OPENING_WORDS for word in self.words)

    def is_arithmetic_start(self) -> bool:

        return self.is_command_start() or (not self.is_word and [word.text for word in self.words] == ["for"])

    def read_test(self) -> None:

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

        end = find_arithmetic_end(self.text, self.index + 2)
        if end < 0:
            return False
        self.read_expansions(self.index + 2, end - 2)
        self.index = end

        return True

    def read_next(self) -> None:

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


def get_segments(text: str, /, *, open_loops: tuple[str, ...] = (), in_group: bool = False, nesting: int = 0) -> list[Segment]:

    return Scanner(text, open_loops=open_loops, in_group=in_group, nesting=nesting).scan()

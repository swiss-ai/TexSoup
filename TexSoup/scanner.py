"""Small source-scanning helpers shared by feature passes.

These helpers intentionally operate on plain source strings. They are not a
tokenizer; they only define low-level TeX comment behavior that source feature
passes should agree on before the parser core runs.
"""

from functools import lru_cache
import re


WORD_CHARS = set(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "@"
)
RAW_ENV_NAMES = (
    "verbatim", "verbatim*", "Verbatim", "lstlisting", "lstlisting*",
    "listing", "alltt", "minted",
)
RAW_DELIMITED_COMMANDS = {"verb", "Verb", "lstinline"}
RAW_BRACED_COMMANDS = {"url", "path", "nolinkurl"}
PROTECTED_SPANS_CACHE_SIZE = 16


def is_escaped(text, pos, escape='\\'):
    """Return whether ``text[pos]`` is escaped by an odd backslash run."""
    backslashes = 0
    i = pos - 1
    while i >= 0 and text[i] == escape:
        backslashes += 1
        i -= 1
    return backslashes % 2 == 1


def starts_comment(text, pos):
    """Return whether ``pos`` starts an unescaped TeX line comment."""
    return pos < len(text) and text[pos] == '%' and not is_escaped(text, pos)


def comment_start(text, start=0, end=None):
    """Return first unescaped ``%`` in ``text[start:end]``, or ``-1``."""
    if end is None:
        end = len(text)
    for i in range(start, end):
        if starts_comment(text, i):
            return i
    return -1


def line_end(text, pos):
    """Return the index immediately after the current line."""
    end = text.find('\n', pos)
    return len(text) if end < 0 else end + 1


def read_control_sequence(text, pos):
    if pos >= len(text) or text[pos] != "\\" or pos + 1 >= len(text):
        return None, pos
    if text[pos + 1] in WORD_CHARS:
        end = pos + 2
        while end < len(text) and text[end] in WORD_CHARS:
            end += 1
        return text[pos:end], end
    return text[pos:pos + 2], pos + 2


def parse_group(text, pos, open_char, close_char):
    if pos >= len(text) or text[pos] != open_char:
        return None
    depth = 1
    i = pos + 1
    out = []
    while i < len(text):
        char = text[i]
        if char == "\\":
            if i + 1 < len(text):
                out.append(text[i:i + 2])
                i += 2
                continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return "".join(out), i + 1
        out.append(char)
        i += 1
    return None


def skip_spaces(text, pos):
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def protected_spans(tex):
    """Return verbatim/raw command spans that source passes must not rewrite."""
    return list(_protected_spans_cached(tex))


@lru_cache(maxsize=PROTECTED_SPANS_CACHE_SIZE)
def _protected_spans_cached(tex):
    return tuple(_merge_spans(_raw_environment_spans(tex) + _raw_command_spans(tex)))


def _raw_environment_spans(tex):
    spans = []
    for env_name in RAW_ENV_NAMES:
        pattern = re.compile(
            r"\\begin\{" + re.escape(env_name) + r"\}.*?"
            r"\\end\{" + re.escape(env_name) + r"\}",
            re.DOTALL,
        )
        spans.extend((m.start(), m.end()) for m in pattern.finditer(tex))
    return sorted(_merge_spans(spans))


def _raw_command_spans(tex):
    spans = []
    i = 0
    while i < len(tex):
        i = _next_raw_command_scan_pos(tex, i)
        if i >= len(tex):
            break
        if starts_comment(tex, i):
            i = line_end(tex, i)
            continue
        command, end = read_control_sequence(tex, i)
        if not command:
            i += 1
            continue

        name = command[1:]
        if name in RAW_DELIMITED_COMMANDS:
            pos = end
            if pos < len(tex) and tex[pos] == "*":
                pos += 1
            if name == "lstinline":
                pos = skip_spaces(tex, pos)
                option = parse_group(tex, pos, "[", "]")
                if option is not None:
                    pos = option[1]
            if pos < len(tex) and not tex[pos].isspace():
                delimiter = tex[pos]
                raw_end = tex.find(delimiter, pos + 1)
                if raw_end >= 0:
                    spans.append((i, raw_end + 1))
                    i = raw_end + 1
                    continue

        if name in RAW_BRACED_COMMANDS:
            pos = skip_spaces(tex, end)
            group = parse_group(tex, pos, "{", "}")
            if group is not None:
                spans.append((i, group[1]))
                i = group[1]
                continue

        i = end
    return spans


def _next_raw_command_scan_pos(tex, pos):
    command_pos = tex.find("\\", pos)
    comment_pos = tex.find("%", pos)
    if command_pos < 0:
        return len(tex) if comment_pos < 0 else comment_pos
    if comment_pos < 0:
        return command_pos
    return min(command_pos, comment_pos)


def _merge_spans(spans):
    merged = []
    for start, end in sorted(spans):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return [tuple(span) for span in merged]

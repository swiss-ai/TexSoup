"""Parse pipeline boundaries.

This module keeps source-level feature passes separate from the parser core.
The core boundary is deliberately small: categorized tokens in, TexSoup tree
out. Source transforms such as simple macro expansion live outside that core so
they can be disabled, tested independently, and replaced incrementally by a
future Rust implementation.
"""

import itertools
import re

from TexSoup.category import categorize
from TexSoup.data import TexEnv
from TexSoup.macros import expand_macros
from TexSoup.reader import read_tex
from TexSoup.scanner import (
    is_escaped,
    line_end,
    parse_group,
    protected_spans,
    read_control_sequence,
    skip_spaces,
    starts_comment,
)
from TexSoup.tlatex import standardize_tlatex_source
from TexSoup.tokens import MATH_ENV_NAMES, tokenize


_EMPTY_MATH_SPACER_RE = re.compile(
    r"(?<!\\)\$\s+\$(?:\s*\\(?:linebreak|nolinebreak|pagebreak|nopagebreak)"
    r"(?![A-Za-z@])(?:\s*\[[^\]]*\])?)?",
    re.IGNORECASE,
)
_TEX_TYPOGRAPHY_REPLACEMENTS = (
    (r"\---", "\u2014"),
    (r"\--", "\u2013"),
    ("---", "\u2014"),
    ("--", "\u2013"),
    ("``", '"'),
    ("''", '"'),
    ("`", "'"),
)
_TYPOGRAPHY_STRUCTURAL_COMMAND_ARITY = {
    "addbibresource": 1,
    "autoref": 1,
    "bibliography": 1,
    "cite": 1,
    "citealp": 1,
    "citealt": 1,
    "citeauthor": 1,
    "citep": 1,
    "citet": 1,
    "citeyear": 1,
    "Cref": 1,
    "cref": 1,
    "eqref": 1,
    "externaldocument": 1,
    "include": 1,
    "includegraphics": 1,
    "input": 1,
    "label": 1,
    "pageref": 1,
    "parencite": 1,
    "ref": 1,
    "subfile": 1,
    "subimport": 2,
    "subref": 1,
    "textcite": 1,
    "vref": 1,
}


def coerce_tex(tex):
    """Return a source string from a string or iterable input."""
    if isinstance(tex, str):
        return tex
    return ''.join(itertools.chain(*tex))


def strip_layout_spacers(tex):
    """Remove empty math used only as a vertical/layout spacer."""
    tex = str(tex)
    spans = protected_spans(tex)
    if not spans:
        return _EMPTY_MATH_SPACER_RE.sub(" ", tex)
    out = []
    pos = 0
    for start, end in spans:
        out.append(_EMPTY_MATH_SPACER_RE.sub(" ", tex[pos:start]))
        out.append(tex[start:end])
        pos = end
    out.append(_EMPTY_MATH_SPACER_RE.sub(" ", tex[pos:]))
    return "".join(out)


def normalize_tex_typography(tex):
    r"""Normalize TeX prose typography outside math and raw spans."""
    tex = str(tex)
    spans = _typography_protected_spans(tex)
    if not spans:
        return _normalize_typography_segment(tex)
    out = []
    pos = 0
    for start, end in spans:
        out.append(_normalize_typography_segment(tex[pos:start]))
        out.append(tex[start:end])
        pos = end
    out.append(_normalize_typography_segment(tex[pos:]))
    return "".join(out)


def _normalize_typography_segment(tex):
    out = []
    i = 0
    while i < len(tex):
        if starts_comment(tex, i):
            end = line_end(tex, i)
            out.append(tex[i:end])
            i = end
            continue
        next_comment = _next_comment_start(tex, i)
        end = len(tex) if next_comment < 0 else next_comment
        out.append(_replace_tex_typography(tex[i:end]))
        i = end
    return "".join(out)


def _replace_tex_typography(tex):
    for old, new in _TEX_TYPOGRAPHY_REPLACEMENTS:
        tex = tex.replace(old, new)
    return tex


def _next_comment_start(tex, pos):
    while True:
        found = tex.find("%", pos)
        if found < 0 or starts_comment(tex, found):
            return found
        pos = found + 1


def _typography_protected_spans(tex):
    raw_spans = protected_spans(tex)
    return _merge_spans(
        raw_spans
        + _math_spans(tex, raw_spans)
        + _structural_command_spans(tex, raw_spans)
    )


def _structural_command_spans(tex, raw_spans):
    spans = []
    raw_index = 0
    i = 0
    while i < len(tex):
        while raw_index < len(raw_spans) and i >= raw_spans[raw_index][1]:
            raw_index += 1
        if raw_index < len(raw_spans) and raw_spans[raw_index][0] <= i:
            i = raw_spans[raw_index][1]
            raw_index += 1
            continue
        if starts_comment(tex, i):
            i = line_end(tex, i)
            continue

        command, end = read_control_sequence(tex, i)
        if not command:
            i += 1
            continue

        name = command[1:]
        if end < len(tex) and tex[end] == "*":
            starred_name = name + "*"
            if name in _TYPOGRAPHY_STRUCTURAL_COMMAND_ARITY:
                end += 1
            elif starred_name in _TYPOGRAPHY_STRUCTURAL_COMMAND_ARITY:
                name = starred_name
                end += 1
        arity = _TYPOGRAPHY_STRUCTURAL_COMMAND_ARITY.get(name)
        if arity is None:
            i = end
            continue

        span_end = _structural_command_end(tex, end, arity)
        if span_end is None:
            i = end
            continue
        spans.append((i, span_end))
        i = span_end
    return spans


def _structural_command_end(tex, pos, arity):
    pos = _skip_optional_groups(tex, pos)
    for _ in range(arity):
        pos = skip_spaces(tex, pos)
        group = parse_group(tex, pos, "{", "}")
        if group is None:
            return None
        pos = group[1]
        pos = _skip_optional_groups(tex, pos)
    return pos


def _skip_optional_groups(tex, pos):
    while True:
        pos = skip_spaces(tex, pos)
        group = parse_group(tex, pos, "[", "]")
        if group is None:
            return pos
        pos = group[1]


def _math_spans(tex, raw_spans):
    spans = []
    raw_index = 0
    i = 0
    while i < len(tex):
        while raw_index < len(raw_spans) and i >= raw_spans[raw_index][1]:
            raw_index += 1
        if raw_index < len(raw_spans) and raw_spans[raw_index][0] <= i:
            i = raw_spans[raw_index][1]
            raw_index += 1
            continue
        if starts_comment(tex, i):
            i = line_end(tex, i)
            continue

        span = _math_switch_span(tex, i)
        if span is not None:
            spans.append(span)
            i = span[1]
            continue

        command, end = read_control_sequence(tex, i)
        if command == r"\begin":
            span = _math_environment_span(tex, i, end)
            if span is not None:
                spans.append(span)
                i = span[1]
                continue
        i = end if command else i + 1
    return spans


def _math_switch_span(tex, pos):
    if tex.startswith(r"\(", pos):
        end = _find_unescaped(tex, r"\)", pos + 2)
        return (pos, end + 2) if end >= 0 else None
    if tex.startswith(r"\[", pos):
        end = _find_unescaped(tex, r"\]", pos + 2)
        return (pos, end + 2) if end >= 0 else None
    if pos < len(tex) and tex[pos] == "$" and not is_escaped(tex, pos):
        delimiter = "$$" if tex.startswith("$$", pos) else "$"
        end = _find_unescaped(tex, delimiter, pos + len(delimiter))
        return (pos, end + len(delimiter)) if end >= 0 else None
    return None


def _math_environment_span(tex, start, pos):
    pos = skip_spaces(tex, pos)
    group = parse_group(tex, pos, "{", "}")
    if group is None:
        return None
    env_name, group_end = group
    env_name = env_name.strip()
    if env_name not in MATH_ENV_NAMES:
        return None
    end_marker = r"\end{" + env_name + "}"
    end = tex.find(end_marker, group_end)
    return (start, end + len(end_marker)) if end >= 0 else None


def _find_unescaped(tex, needle, pos):
    while True:
        found = tex.find(needle, pos)
        if found < 0 or not is_escaped(tex, found):
            return found
        pos = found + len(needle)


def _merge_spans(spans):
    merged = []
    for start, end in sorted(spans):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return [tuple(span) for span in merged]


DEFAULT_SOURCE_TRANSFORMS = (
    strip_layout_spacers,
    expand_macros,
    standardize_tlatex_source,
    normalize_tex_typography,
)


def standardize_source(tex, expand=True, transforms=None):
    """Run source-level standardization passes before the parser core.

    ``expand`` preserves the historical boolean API. Tests for Rust parity
    should usually call ``read_core`` directly, then add feature passes one by
    one through this function.
    """
    tex = coerce_tex(tex)
    if transforms is None:
        transforms = DEFAULT_SOURCE_TRANSFORMS if expand else ()
    for transform in transforms:
        tex = transform(tex)
    return tex


def prepare_source(tex, expand=True, transforms=None):
    """Backward-compatible alias for ``standardize_source``."""
    return standardize_source(tex, expand=expand, transforms=transforms)


def read_core(tex, skip_envs=(), tolerance=0):
    """Parse already-prepared LaTeX source into the TexSoup tree.

    This is the core grammar/token/tree boundary. It intentionally does not
    expand macros or apply arXiv-specific source normalization.
    """
    buf = categorize(tex)
    buf = tokenize(buf)
    buf = read_tex(buf, skip_envs=skip_envs, tolerance=tolerance)
    return TexEnv('[tex]', begin='', end='', contents=buf)


def read(tex, skip_envs=(), tolerance=0, expand=False):
    """Parse source and return ``(tree, source)``.

    Source standardization is opt-in so the public parser remains lossless by
    default. Corpus converters can call :func:`standardize_source` explicitly
    or pass ``expand=True`` when they want the full preprocessing pipeline.
    """
    tex = standardize_source(tex, expand=expand)
    return read_core(tex, skip_envs=skip_envs, tolerance=tolerance), tex

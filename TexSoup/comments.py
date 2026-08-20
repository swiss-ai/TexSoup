"""Source-level handling for TeX comments and ``comment`` package blocks.

These helpers are feature passes, not parser-core behavior. They are kept as
small string-to-string transforms so a future Rust implementation can reproduce
and test them independently from tokenization and tree construction.
"""

from TexSoup.scanner import comment_start as _unescaped_percent
from TexSoup.scanner import line_end as _line_end
from TexSoup.scanner import protected_spans as _protected_spans
from TexSoup.scanner import starts_comment as _starts_comment


_DIRECTIVE_COMMANDS = {
    'excludecomment': False,
    'includecomment': True,
}
_ALPHA_CHARS = set(
    'abcdefghijklmnopqrstuvwxyz'
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    '@'
)


def strip_tex_comments(tex):
    """Remove unescaped line comments while preserving verbatim-like spans."""
    spans = _active_protected_spans(tex)
    pieces = []
    cursor = 0
    for start, end in spans:
        pieces.append(_strip_comments_unprotected(tex[cursor:start]))
        pieces.append(tex[start:end])
        cursor = end
    pieces.append(_strip_comments_unprotected(tex[cursor:]))
    return ''.join(pieces)


def apply_comment_package(tex):
    r"""Apply simple ``\includecomment`` / ``\excludecomment`` declarations.

    Excluded environments are removed with their contents. Included environments
    keep their contents but lose the synthetic wrapper. The literal
    ``comment``/``comment*`` environments are always excluded.
    """
    state, directive_spans = collect_comment_directives(tex)
    excluded = {name for name, included in state.items() if not included}
    included = {name for name, included in state.items() if included}
    excluded.update(('comment', 'comment*'))

    drop_spans = (
        directive_spans
        + _environment_block_spans(tex, excluded)
        + _environment_marker_spans(tex, included)
    )
    return _replace_spans(tex, drop_spans, '')


def collect_comment_directives(tex):
    """Return ``({env_name: included_bool}, declaration_spans)``."""
    spans = _active_protected_spans(tex)
    span_index = 0
    state = {}
    directive_spans = []
    i = 0
    while i < len(tex):
        while span_index < len(spans) and i >= spans[span_index][1]:
            span_index += 1
        if span_index < len(spans) and spans[span_index][0] <= i:
            i = spans[span_index][1]
            continue
        if _starts_comment(tex, i):
            i = _line_end(tex, i)
            continue

        command, end = _read_command(tex, i)
        if command not in _DIRECTIVE_COMMANDS:
            i += 1
            continue
        pos = _skip_space(tex, end)
        group = _read_group(tex, pos, '{', '}')
        if group is None:
            i = end
            continue
        env_name = group[0].strip()
        if env_name:
            state[env_name] = _DIRECTIVE_COMMANDS[command]
            directive_spans.append((i, group[1]))
        i = group[1]
    return state, directive_spans


def _strip_comments_unprotected(text):
    lines = []
    for line in text.splitlines(keepends=True):
        comment = _unescaped_percent(line)
        if comment < 0:
            lines.append(line)
            continue
        newline = ''
        if line.endswith('\r\n'):
            newline = '\r\n'
        elif line.endswith('\n'):
            newline = '\n'
        elif line.endswith('\r'):
            newline = '\r'
        lines.append(line[:comment] + newline)
    return ''.join(lines)


def _environment_block_spans(tex, env_names):
    if not env_names:
        return []
    spans = _active_protected_spans(tex)
    results = []
    i = 0
    while i < len(tex):
        if _inside_spans(i, spans):
            i = _span_end(i, spans)
            continue
        if _starts_comment(tex, i):
            i = _line_end(tex, i)
            continue
        parsed = _read_environment_marker(tex, i)
        if parsed is None or parsed[0] != 'begin' or parsed[1] not in env_names:
            i += 1
            continue
        end = _find_environment_end(tex, parsed[1], parsed[2], spans)
        if end is None:
            i = parsed[2]
            continue
        results.append((i, end))
        i = end
    return _merge_spans(results)


def _environment_marker_spans(tex, env_names):
    if not env_names:
        return []
    spans = _active_protected_spans(tex)
    results = []
    i = 0
    while i < len(tex):
        if _inside_spans(i, spans):
            i = _span_end(i, spans)
            continue
        if _starts_comment(tex, i):
            i = _line_end(tex, i)
            continue
        parsed = _read_environment_marker(tex, i)
        if parsed is not None and parsed[1] in env_names:
            results.append((i, parsed[2]))
            i = parsed[2]
            continue
        i += 1
    return results


def _find_environment_end(tex, env_name, pos, protected_spans):
    depth = 1
    i = pos
    while i < len(tex):
        if _inside_spans(i, protected_spans):
            i = _span_end(i, protected_spans)
            continue
        if _starts_comment(tex, i):
            i = _line_end(tex, i)
            continue
        parsed = _read_environment_marker(tex, i)
        if parsed is None or parsed[1] != env_name:
            i += 1
            continue
        if parsed[0] == 'begin':
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return parsed[2]
        i = parsed[2]
    return None


def _read_environment_marker(tex, pos):
    command, end = _read_command(tex, pos)
    if command not in ('begin', 'end'):
        return None
    group = _read_group(tex, _skip_space(tex, end), '{', '}')
    if group is None:
        return None
    env_name = group[0].strip()
    if not env_name:
        return None
    return command, env_name, group[1]


def _read_command(tex, pos):
    if pos >= len(tex) or tex[pos] != '\\' or pos + 1 >= len(tex):
        return None, pos
    if tex[pos + 1] in _ALPHA_CHARS:
        end = pos + 2
        while end < len(tex) and tex[end] in _ALPHA_CHARS:
            end += 1
        if end < len(tex) and tex[end] == '*':
            end += 1
        return tex[pos + 1:end], end
    return tex[pos + 1:pos + 2], pos + 2


def _read_group(tex, pos, open_char, close_char):
    if pos >= len(tex) or tex[pos] != open_char:
        return None
    depth = 1
    i = pos + 1
    while i < len(tex):
        if tex[i] == '\\':
            i += 2
            continue
        if _starts_comment(tex, i):
            i = _line_end(tex, i)
            continue
        if tex[i] == open_char:
            depth += 1
        elif tex[i] == close_char:
            depth -= 1
            if depth == 0:
                return tex[pos + 1:i], i + 1
        i += 1
    return None


def _replace_spans(tex, spans, replacement):
    if not spans:
        return tex
    pieces = []
    cursor = 0
    for start, end in _merge_spans(spans):
        if start < cursor:
            continue
        pieces.append(tex[cursor:start])
        pieces.append(replacement)
        cursor = end
    pieces.append(tex[cursor:])
    return ''.join(pieces)


def _active_protected_spans(tex):
    spans = _protected_spans(tex)
    return [
        (start, end) for start, end in spans
        if not _position_is_commented(tex, start, spans)
    ]


def _merge_spans(spans):
    merged = []
    for start, end in sorted(spans):
        if start >= end:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return [tuple(span) for span in merged]


def _inside_spans(pos, spans):
    return any(start <= pos < end for start, end in spans)


def _span_end(pos, spans):
    for start, end in spans:
        if start <= pos < end:
            return end
    return pos + 1


def _skip_space(tex, pos):
    while pos < len(tex) and tex[pos].isspace():
        pos += 1
    return pos


def _position_is_commented(tex, pos, protected_spans=()):
    line_start = max(tex.rfind('\n', 0, pos), tex.rfind('\r', 0, pos)) + 1
    i = line_start
    while i < pos:
        protected_end = _span_end_if_inside(i, protected_spans)
        if protected_end is not None:
            i = min(protected_end, pos)
            continue
        if _starts_comment(tex, i):
            return True
        i += 1
    return False


def _span_end_if_inside(pos, spans):
    for start, end in spans:
        if start <= pos < end:
            return end
    return None

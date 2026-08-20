r"""Source standardization for tla2tex generated TLA+ snippets.

The tla2tex style emits useful specifications through layout commands such as
``\@x{...}``, ``\@s{...}``, and ``\.{...}``. Those commands are not prose, but
their arguments often are the scientific content. This pass strips only that
layout shell after a source has explicitly entered ``\tlatex`` mode.
"""

from TexSoup.scanner import (
    line_end,
    parse_group,
    protected_spans,
    read_control_sequence,
    skip_spaces,
    starts_comment,
)
import re


_TLA_LINE_COMMANDS = {r"\@x", r"\@xx", r"\@y"}
_TLA_SPACE_COMMANDS = {r"\@s", r"\hspace", r"\hspace*", r"\vspace", r"\vspace*"}
_TLA_DROP_ARG_COUNTS = {
    r"\@pvspace": 1,
    r"\setboolean": 2,
    r"\setstretch": 1,
    r"\fontsize": 2,
    r"\setlength": 2,
    r"\addtolength": 2,
}
_TLA_DROP_NO_ARG = {
    r"\batchmode",
    r"\centering",
    r"\footnotesize",
    r"\scriptsize",
    r"\selectfont",
    r"\small",
    r"\tlasize",
    r"\moduleLeftDash",
    r"\moduleRightDash",
    r"\midbar",
    r"\bottombar",
    r"\tstrut",
    r"\rstrut",
    r"\xtstrut",
    r"\normalsize",
}
_TLA_KEEP_LAST_ARG_COUNTS = {
    r"\text": 1,
    r"\textsc": 1,
    r"\textbf": 1,
    r"\textit": 1,
    r"\textrm": 1,
    r"\mathrm": 1,
    r"\mathit": 1,
    r"\mathbf": 1,
    r"\mbox": 1,
    r"\ensuremath": 1,
    r"\makebox": 1,
    r"\raisebox": 2,
    r"\resizebox": 3,
}
_TLA_LAYOUT_TEXT_RE = re.compile(
    r"(?:[-+]?\d+(?:\.\d+)?(?:pt|em|ex|cm|in|\\linewidth|\\textwidth|\\baselineskip)|!)+"
)


def standardize_tlatex_source(tex):
    r"""Expose useful TLA+ text from tla2tex layout wrappers.

    The transform is intentionally dormant until a ``\tlatex`` command is seen,
    which avoids rewriting ordinary LaTeX macro definitions from ``tlatex.sty``.
    """
    if r"\tlatex" not in tex and r"\@x{" not in tex:
        return tex
    return _rewrite_tlatex_fragment(tex, active=False)


def _rewrite_tlatex_fragment(tex, active):
    spans = protected_spans(tex)
    span_index = 0
    out = []
    env_stack = []
    active_scope_depth = None
    i = 0
    while i < len(tex):
        while span_index < len(spans) and i >= spans[span_index][1]:
            span_index += 1
        if span_index < len(spans) and spans[span_index][0] <= i:
            start, end = spans[span_index]
            out.append(tex[i:end])
            i = end
            span_index += 1
            continue
        if starts_comment(tex, i):
            end = line_end(tex, i)
            out.append(tex[i:end])
            i = end
            continue

        command, end = read_control_sequence(tex, i)
        if not command:
            if active:
                layout = _TLA_LAYOUT_TEXT_RE.match(tex, i)
                if layout is not None:
                    i = layout.end()
                    continue
            out.append(tex[i])
            i += 1
            continue

        if command == r"\begin":
            env_group = _read_one_group(tex, end)
            if env_group is None:
                out.append(tex[i:end])
                i = end
                continue
            env_name, env_group_end = env_group
            pos = skip_spaces(tex, env_group_end)
            option = parse_group(tex, pos, "[", "]")
            out.append(tex[i:env_group_end])
            env_stack.append(env_name.strip())
            if option is not None and _env_contains_tlatex(tex, option[1], env_name.strip()):
                i = option[1]
            else:
                i = env_group_end
            continue

        if command == r"\end":
            env_group = _read_one_group(tex, end)
            if env_group is None:
                out.append(tex[i:end])
                i = end
                continue
            env_name, env_group_end = env_group
            out.append(tex[i:env_group_end])
            if env_stack:
                env_stack.pop()
            if (
                active
                and active_scope_depth is not None
                and len(env_stack) < active_scope_depth
            ):
                active = False
                active_scope_depth = None
            i = env_group_end
            continue

        if command == r"\tlatex":
            active = True
            active_scope_depth = len(env_stack)
            out.append("\n")
            i = end
            continue
        if not active:
            if (
                env_stack
                and command in _TLA_DROP_NO_ARG
                and _env_contains_tlatex(tex, end, env_stack[-1])
            ):
                i = end
                continue
            out.append(tex[i:end])
            i = end
            continue

        rewritten = _rewrite_tlatex_command(tex, command, end, active=True)
        if rewritten is None:
            out.append(tex[i:end])
            i = end
            continue
        replacement, i = rewritten
        out.append(replacement)
    return "".join(out)


def _env_contains_tlatex(tex, pos, env_name):
    if not env_name:
        return False
    end_marker = r"\end{" + env_name + "}"
    end = tex.find(end_marker, pos)
    search_end = len(tex) if end < 0 else end
    return r"\tlatex" in tex[pos:search_end]


def _rewrite_tlatex_command(tex, command, end, active):
    if command in _TLA_LINE_COMMANDS:
        arg = _read_one_group(tex, end)
        if arg is None:
            return None
        body, span_end = arg
        rendered = _rewrite_tlatex_fragment(body, active=active).strip()
        return "\n" + rendered + "\n", span_end

    if command == r"\.":
        arg = _read_one_group(tex, end)
        if arg is not None:
            body, span_end = arg
            return _rewrite_tlatex_fragment(body, active=active), span_end
        pos = skip_spaces(tex, end)
        token, token_end = read_control_sequence(tex, pos)
        if token:
            return token, token_end
        if pos < len(tex):
            return tex[pos], pos + 1
        return "", end

    if command in _TLA_SPACE_COMMANDS:
        arg = _read_one_group(tex, end)
        return (" ", arg[1]) if arg is not None else (" ", end)

    if command in _TLA_DROP_ARG_COUNTS:
        args = _read_required_groups(tex, end, _TLA_DROP_ARG_COUNTS[command])
        return ("", args[-1][1]) if args is not None else ("", end)

    if command in _TLA_DROP_NO_ARG:
        return "", end

    if command == r"\textcolor":
        args = _read_required_groups(tex, end, 2)
        if args is None:
            return None
        return _rewrite_tlatex_fragment(args[-1][0], active=active), args[-1][1]

    if command == r"\color":
        arg = _read_one_group(tex, end)
        return ("", arg[1]) if arg is not None else ("", end)

    if command in _TLA_KEEP_LAST_ARG_COUNTS:
        args = _read_required_groups(tex, end, _TLA_KEEP_LAST_ARG_COUNTS[command])
        if args is None:
            return None
        return _rewrite_tlatex_fragment(args[-1][0], active=active), args[-1][1]

    if command == r"\rule":
        args = _read_required_groups(tex, end, 2)
        if args is None:
            return "", end
        return "", args[-1][1]

    return None


def _read_one_group(tex, pos):
    pos = skip_spaces(tex, pos)
    return parse_group(tex, pos, "{", "}")


def _read_required_groups(tex, pos, count):
    args = []
    for _ in range(8):
        pos = skip_spaces(tex, pos)
        option = parse_group(tex, pos, "[", "]")
        if option is None:
            break
        pos = option[1]
    for _ in range(count):
        pos = skip_spaces(tex, pos)
        group = parse_group(tex, pos, "{", "}")
        if group is None:
            return None
        args.append(group)
        pos = group[1]
        for _ in range(8):
            pos = skip_spaces(tex, pos)
            option = parse_group(tex, pos, "[", "]")
            if option is None:
                break
            pos = option[1]
    return args

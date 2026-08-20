"""Conservative source-level macro expansion for common paper aliases."""

import re

from TexSoup.scanner import line_end as _line_end
from TexSoup.scanner import parse_group as _parse_group
from TexSoup.scanner import protected_spans as _protected_spans
from TexSoup.scanner import read_control_sequence as _read_control_sequence
from TexSoup.scanner import skip_spaces as _skip_spaces
from TexSoup.scanner import starts_comment as _starts_comment


_DEF_COMMANDS = {"def", "gdef", "edef", "xdef"}
_LATEX_COMMANDS = {"newcommand", "renewcommand", "providecommand"}
_DEFINITION_COMMANDS = _DEF_COMMANDS | _LATEX_COMMANDS | {"DeclareMathOperator"}
_ENVIRONMENT_COMMANDS = {"newenvironment", "renewenvironment", "provideenvironment"}
_MAX_ARGS = 2
_MAX_BODY_CHARS = 500
_SOURCE_WRAPPER_MAX_BODY_CHARS = 2000
_SOURCE_WRAPPER_ENVS = (
    "figure", "figure*", "table", "table*", "wrapfigure", "subfigure",
    "subtable", "tikzpicture", "tabular", "tabular*", "lstlisting",
    "listing", "minted", "quantikz", "tcblisting", "tcblisting*",
)
_SOURCE_WRAPPER_RE = re.compile(
    r"\\includegraphics\*?|\\begin\{(?:%s)\}"
    % "|".join(re.escape(name) for name in _SOURCE_WRAPPER_ENVS)
)
_UNSAFE_BODY_RE = re.compile(
    r"\\(?:def|gdef|edef|xdef|let|futurelet|newcommand|renewcommand|"
    r"providecommand|DeclareRobustCommand|csname|expandafter|catcode|"
    r"input|include|write|if[A-Za-z@]*)\b"
)


class Macro(object):
    def __init__(self, name, nargs, body, optional_default=None):
        self.name = name
        self.nargs = nargs
        self.body = body
        self.optional_default = optional_default


class EnvironmentAlias(object):
    def __init__(self, name, target):
        self.name = name
        self.target = target


def _builtin_simple_macros():
    return {
        r"\Bar": Macro(r"\Bar", 1, r"\bar{#1}"),
        r"\bigO": Macro(r"\bigO", 0, r"\mathcal{O}"),
    }


def expand_macros(tex, max_passes=1):
    r"""Expand simple, obvious user macros before parsing.

    This is intentionally not a TeX interpreter. It handles small, non-optional
    paper aliases such as ``\be`` -> ``\begin{equation}`` and simple wrappers
    such as ``\figref{X}`` -> ``Figure~\ref{X}``. Expansion is single-pass by
    default and skips macro definitions themselves.
    """
    for _ in range(max_passes):
        expanded, changed = _expand_macros_once(tex)
        if not changed:
            return _expand_label_relation_macros(tex)
        if expanded == tex:
            return _expand_label_relation_macros(tex)
        tex = expanded
    return _expand_label_relation_macros(tex)


def _expand_macros_once(tex):
    macros = _builtin_simple_macros()
    source_defined_macros = set()
    definition_aliases = {}
    environment_aliases = {}
    protected_spans = _protected_spans(tex)
    span_index = 0
    out = []
    changed = False
    i = 0

    while i < len(tex):
        while span_index < len(protected_spans) and i >= protected_spans[span_index][1]:
            span_index += 1
        if span_index < len(protected_spans) and protected_spans[span_index][0] <= i:
            start, end = protected_spans[span_index]
            out.append(tex[i:end])
            i = end
            span_index += 1
            continue
        if _starts_comment(tex, i):
            end = _line_end(tex, i)
            out.append(tex[i:end])
            i = end
            continue

        command, end = _read_control_sequence(tex, i)
        if not command:
            out.append(tex[i])
            i += 1
            continue

        env_parsed = _parse_environment_alias_at(tex, i, command, end)
        if env_parsed is not None:
            alias, span = env_parsed
            if alias is not None:
                environment_aliases[alias.name] = alias.target
            out.append(tex[i:span[1]])
            i = span[1]
            continue

        parsed = _parse_definition_at(tex, i, command, end, definition_aliases)
        if parsed is not None:
            macro, span = parsed
            command_name = definition_aliases.get(command[1:], command[1:])
            if macro is not None:
                alias_target = _definition_alias_target(macro)
                if alias_target is not None:
                    definition_aliases[macro.name[1:]] = alias_target
                elif _is_safe_macro(macro):
                    if command_name != "providecommand" or macro.name not in source_defined_macros:
                        macros[macro.name] = macro
                        source_defined_macros.add(macro.name)
            if command_name != command[1:]:
                out.append("\\" + command_name + tex[end:span[1]])
            else:
                out.append(tex[i:span[1]])
            i = span[1]
            continue

        env_use = _expand_environment_alias_use(tex, command, end, environment_aliases)
        if env_use is not None:
            replacement, span_end = env_use
            out.append(replacement)
            i = span_end
            changed = True
            continue

        macro = macros.get(command)
        if macro is None:
            out.append(tex[i])
            i += 1
            continue

        parsed_args = _parse_macro_use_args(tex, end, macro)
        if parsed_args is None:
            out.append(tex[i])
            i += 1
            continue
        args, j = parsed_args

        out.append(_substitute(macro.body, args))
        i = j
        changed = True

    return "".join(out), changed


def collect_simple_macros(tex):
    macros = {}
    raw_spans = _protected_spans(tex)
    spans = list(raw_spans)
    span_index = 0
    i = 0
    while i < len(tex):
        while span_index < len(raw_spans) and i >= raw_spans[span_index][1]:
            span_index += 1
        if span_index < len(raw_spans) and raw_spans[span_index][0] <= i:
            i = raw_spans[span_index][1]
            continue
        if _starts_comment(tex, i):
            i = _line_end(tex, i)
            continue
        command, end = _read_control_sequence(tex, i)
        if not command:
            i += 1
            continue
        parsed = _parse_definition_at(tex, i, command, end)

        if parsed is None:
            i = end
            continue

        macro, span = parsed
        if macro is not None and _is_safe_macro(macro):
            macros[macro.name] = macro
        spans.append(span)
        i = span[1]
    return macros, spans


def _parse_definition_at(tex, start, command, end, definition_aliases=None):
    name = command[1:]
    effective_name = (definition_aliases or {}).get(name, name)
    star = ""
    if end < len(tex) and tex[end] == "*":
        star = "*"

    if effective_name in _DEF_COMMANDS and not star:
        return _parse_primitive_definition(tex, start, end)
    if effective_name in _LATEX_COMMANDS:
        return _parse_latex_definition(tex, start, end + len(star))
    if effective_name == "DeclareMathOperator":
        return _parse_math_operator(tex, start, end + len(star))
    return None


def _definition_alias_target(macro):
    if macro.nargs != 0 or macro.optional_default is not None:
        return None
    body = macro.body.strip()
    command, end = _read_control_sequence(body, 0)
    if not command or end != len(body):
        return None
    target = command[1:]
    return target if target in _DEFINITION_COMMANDS else None


def expand_macro_uses(tex, macros, skip_spans):
    if not macros:
        return tex

    spans = sorted(skip_spans)
    span_index = 0
    out = []
    i = 0
    while i < len(tex):
        if span_index < len(spans) and i >= spans[span_index][1]:
            span_index += 1
            continue
        if span_index < len(spans) and spans[span_index][0] <= i:
            start, end = spans[span_index]
            out.append(tex[i:end])
            i = end
            span_index += 1
            continue
        if _starts_comment(tex, i):
            end = _line_end(tex, i)
            out.append(tex[i:end])
            i = end
            continue

        command, end = _read_control_sequence(tex, i)
        macro = macros.get(command)
        if macro is None:
            out.append(tex[i])
            i += 1
            continue

        parsed_args = _parse_macro_use_args(tex, end, macro)
        if parsed_args is None:
            out.append(tex[i])
            i += 1
            continue
        args, j = parsed_args

        out.append(_substitute(macro.body, args))
        i = j

    return "".join(out)


def _expand_label_relation_macros(tex):
    protected_spans = _protected_spans(tex)
    span_index = 0
    out = []
    changed = False
    i = 0
    while i < len(tex):
        while span_index < len(protected_spans) and i >= protected_spans[span_index][1]:
            span_index += 1
        if span_index < len(protected_spans) and protected_spans[span_index][0] <= i:
            start, end = protected_spans[span_index]
            out.append(tex[i:end])
            i = end
            span_index += 1
            continue
        if _starts_comment(tex, i):
            end = _line_end(tex, i)
            out.append(tex[i:end])
            i = end
            continue

        command, end = _read_control_sequence(tex, i)
        if command != r"\labelrel":
            out.append(tex[i])
            i += 1
            continue

        pos = _skip_spaces(tex, end)
        relation = ""
        relation_command, relation_end = _read_control_sequence(tex, pos)
        if relation_command:
            relation = relation_command
            pos = relation_end
        elif pos < len(tex) and tex[pos] != "{":
            relation = tex[pos]
            pos += 1
        pos = _skip_spaces(tex, pos)
        group = _parse_group(tex, pos, "{", "}")
        if group is None:
            out.append(tex[i])
            i += 1
            continue
        key, span_end = group
        out.append(relation + r"\label{" + key.strip() + "}")
        i = span_end
        changed = True

    return "".join(out) if changed else tex


def _parse_primitive_definition(tex, start, pos):
    pos = _skip_spaces(tex, pos)
    target, pos = _read_control_sequence(tex, pos)
    if not target:
        return None
    param_start = pos
    while pos < len(tex) and tex[pos] != "{":
        pos += 1
    if pos >= len(tex):
        return None
    param_text = tex[param_start:pos].strip()
    nargs = _param_count(param_text)
    if nargs is None:
        return None
    group = _parse_group(tex, pos, "{", "}")
    if group is None:
        return None
    body, end = group
    body = _standardize_visual_macro_body(body, nargs, target=target)
    return Macro(target, nargs, body), (start, end)


def _parse_latex_definition(tex, start, pos):
    pos = _skip_spaces(tex, pos)
    target = None
    group = _parse_group(tex, pos, "{", "}")
    if group is not None:
        raw_target, pos = group
        raw_target = raw_target.strip()
        control, control_end = _read_control_sequence(raw_target, 0)
        if control and control_end == len(raw_target):
            target = control
    else:
        target, pos = _read_control_sequence(tex, pos)
    if not target:
        return None

    pos = _skip_spaces(tex, pos)
    nargs = 0
    optional_default = None
    first_optional = _parse_group(tex, pos, "[", "]")
    if first_optional is not None and first_optional[0].strip().isdigit():
        nargs = int(first_optional[0].strip())
        pos = first_optional[1]
        pos = _skip_spaces(tex, pos)
        default_group = _parse_group(tex, pos, "[", "]")
        if default_group is not None:
            if nargs < 1:
                return None
            optional_default = default_group[0]
            pos = default_group[1]

    group = _parse_group(tex, pos, "{", "}")
    if group is None:
        return None
    body, end = group
    body = _standardize_visual_macro_body(body, nargs, target=target)
    return Macro(target, nargs, body, optional_default=optional_default), (start, end)


def _parse_math_operator(tex, start, pos):
    pos = _skip_spaces(tex, pos)
    group = _parse_group(tex, pos, "{", "}")
    if group is None:
        return None
    raw_target, pos = group
    raw_target = raw_target.strip()
    target, target_end = _read_control_sequence(raw_target, 0)
    if not target or target_end != len(raw_target):
        return None
    pos = _skip_spaces(tex, pos)
    group = _parse_group(tex, pos, "{", "}")
    if group is None:
        return None
    body, end = group
    return Macro(target, 0, r"\operatorname{" + body + "}"), (start, end)


def _parse_environment_alias_at(tex, start, command, end):
    name = command[1:]
    star = ""
    if end < len(tex) and tex[end] == "*":
        star = "*"
    if name not in _ENVIRONMENT_COMMANDS:
        return None

    pos = _skip_spaces(tex, end + len(star))
    group = _parse_group(tex, pos, "{", "}")
    if group is None:
        return None
    env_name, pos = group
    env_name = env_name.strip()
    if not env_name:
        return None

    pos = _skip_spaces(tex, pos)
    first_optional = _parse_group(tex, pos, "[", "]")
    if first_optional is not None and first_optional[0].strip().isdigit():
        if first_optional[0].strip() not in {"", "0"}:
            return None
        pos = _skip_spaces(tex, first_optional[1])
        if _parse_group(tex, pos, "[", "]") is not None:
            return None

    begin_group = _parse_group(tex, pos, "{", "}")
    if begin_group is None:
        return None
    begin_body, pos = begin_group
    pos = _skip_spaces(tex, pos)
    end_group = _parse_group(tex, pos, "{", "}")
    if end_group is None:
        return None
    end_body, pos = end_group

    target = _environment_alias_target(begin_body, end_body)
    alias = EnvironmentAlias(env_name, target) if target else None
    return alias, (start, pos)


def _environment_alias_target(begin_body, end_body):
    begin = begin_body.strip()
    end = end_body.strip()
    match = re.match(r"\\begin\{(?P<target>[^{}]+)\}", begin)
    if not match:
        return None
    target = match.group("target").strip()
    rest = begin[match.end():]
    if not re.fullmatch(r"(?:\s|\\(?:rm|it|sl|sf|tt|bf|normalfont|rmfamily|itshape|slshape|sffamily|ttfamily|bfseries|mdseries|upshape|relax)\b)*", rest):
        return None
    if end != r"\end{" + target + "}":
        return None
    return target


def _expand_environment_alias_use(tex, command, end, aliases):
    if command not in {r"\begin", r"\end"}:
        return None
    pos = _skip_spaces(tex, end)
    group = _parse_group(tex, pos, "{", "}")
    if group is None:
        return None
    env_name, span_end = group
    target = aliases.get(env_name.strip())
    if target is None:
        return None
    return command + "{" + target + "}", span_end


def _is_safe_macro(macro):
    if macro.nargs < 0 or macro.nargs > _MAX_ARGS:
        return False
    max_body_chars = (
        _SOURCE_WRAPPER_MAX_BODY_CHARS
        if _SOURCE_WRAPPER_RE.search(macro.body)
        else _MAX_BODY_CHARS
    )
    if len(macro.body) > max_body_chars:
        return False
    if _UNSAFE_BODY_RE.search(macro.body):
        return False
    used = set(int(digit) for digit in re.findall(r"#([1-9])", macro.body))
    if any(index > macro.nargs for index in used):
        return False
    scrubbed = re.sub(r"#[1-9]", "", macro.body)
    if "#" in scrubbed:
        return False
    return True


def _parse_macro_use_args(tex, pos, macro):
    args = []
    j = pos
    required = macro.nargs
    if macro.optional_default is not None:
        j = _skip_spaces(tex, j)
        optional = _parse_group(tex, j, "[", "]")
        if optional is not None:
            args.append(optional[0])
            j = optional[1]
        else:
            args.append(macro.optional_default)
        required -= 1
    for _ in range(required):
        j = _skip_spaces(tex, j)
        group = _parse_group(tex, j, "{", "}")
        if group is None:
            return None
        arg, j = group
        args.append(arg)
    return args, j


_INCLUDEGRAPHICS_PLACEHOLDER_RE = re.compile(
    r"\\includegraphics\*?(?:\s*\[[^\]]*\])?\s*\{\s*#(?P<idx>[1-9])\s*\}",
    re.DOTALL,
)
_SOLE_INCLUDEGRAPHICS_RE = re.compile(
    r"^\s*(?:\\protect\s*)?\\includegraphics\*?"
    r"(?:\s*\[[^\]]*\])?\s*\{\s*(?P<name>[^{}]+?)\s*\}\s*$",
    re.DOTALL,
)


def _standardize_visual_macro_body(body, nargs, target=None):
    r"""Collapse simple image wrapper macro bodies to their image include.

    Many arXiv sources define visual macros that wrap a single
    ``\includegraphics{#k}`` in TikZ/adjustbox/layout commands and then use the
    macro inside figure grids. Expanding the full body exposes drawing syntax
    downstream; exposing the underlying image include keeps the standardized
    representation simple.
    """
    if r"\includegraphics" not in body:
        return body
    inline_logo_text = _inline_logo_text_macro(target, body, nargs)
    if inline_logo_text is not None:
        return inline_logo_text
    matches = list(_INCLUDEGRAPHICS_PLACEHOLDER_RE.finditer(body))
    if len(matches) != 1:
        return body
    index = int(matches[0].group("idx"))
    if index < 1 or index > nargs:
        return body
    return r"\includegraphics{#" + str(index) + "}"


def _inline_logo_text_macro(target, body, nargs):
    if nargs != 0 or not target:
        return None
    match = _SOLE_INCLUDEGRAPHICS_RE.match(body)
    if match is None:
        return None
    macro_stem = target.lstrip("\\")
    if not macro_stem.lower().endswith("logo"):
        return None
    image_stem = re.sub(r"\.[A-Za-z0-9]+$", "", match.group("name").replace("\\", "/").rsplit("/", 1)[-1])
    if image_stem.lower() != macro_stem.lower():
        return None
    text = macro_stem[:-4]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9.+#-]{0,15}", text):
        return None
    return text


def _substitute(body, args):
    for index, value in enumerate(args, start=1):
        body = body.replace("#%d" % index, value)
    return body


def _param_count(param_text):
    if not param_text:
        return 0
    compact = re.sub(r"\s+", "", param_text)
    matches = re.findall(r"#([1-9])", compact)
    if not matches:
        return None
    expected = "".join("#%d" % i for i in range(1, len(matches) + 1))
    if compact != expected:
        return None
    return len(matches)

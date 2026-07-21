"""Table source normalization helpers.

These helpers sit above the parser core. They expose reusable table cleanup
primitives without committing TexSoup to a Markdown/table rendering contract.
Converters can consume the normalized tree/text and map it to their own IR.
"""

import re

from TexSoup.data import TexNode


TABLE_INNER_ENVS = {
    "array",
    "longtblr",
    "longtblr*",
    "ruledtabular",
    "tabular",
    "tabular*",
    "tabularx",
    "tabulary",
    "talltblr",
    "talltblr*",
    "tblr",
    "tblr*",
    "threeparttable",
}

TABLE_SPACING_CMDS = {
    "enspace",
    "hfil",
    "hfill",
    "medspace",
    "negthinspace",
    "quad",
    "qquad",
    "thickspace",
    "thinspace",
    "vfil",
    "vfill",
}

TABLE_DROP_CMD_ARITY = {
    "addlinespace": 0,
    "arrayrulecolor": 1,
    "bottomrule": 0,
    "captionsetup": 1,
    "cellcolor": 1,
    "centering": 0,
    "cline": 1,
    "cmidrule": 1,
    "columncolor": 1,
    "definecolor": 3,
    "hhline": 1,
    "hline": 0,
    "midrule": 0,
    "noalign": 1,
    "renewcommand": 2,
    "raggedleft": 0,
    "raggedright": 0,
    "rowcolor": 1,
    "rowcolors": 3,
    "rule": 2,
    "sethline": 2,
    "setlength": 2,
    "sisetup": 1,
    "spacer": 1,
    "sr": 1,
    "toprule": 0,
}

TABLE_WRAPPER_CMD_ARITY = {
    "colorbox": 2,
    "colhead": 1,
    "emph": 1,
    "fcolorbox": 3,
    "makecell": 1,
    "multicolumn": 3,
    "multirow": 3,
    "parbox": 2,
    "rotatebox": 2,
    "tabt": 1,
    "tabtt": 1,
    "textbf": 1,
    "textcolor": 2,
    "textit": 1,
    "textrm": 1,
    "textsc": 1,
    "textsf": 1,
    "textsl": 1,
    "texttt": 1,
    "thead": 1,
    "underline": 1,
}


def _env_arg_body(arg):
    return _strip_outer_groups(str(arg).strip())


def _strip_outer_groups(text):
    text = str(text).strip()
    while len(text) >= 2 and (
        (text[0] == "{" and text[-1] == "}")
        or (text[0] == "[" and text[-1] == "]")
    ):
        text = text[1:-1].strip()
    return text


def _consume_text_prefix(text, target):
    target = target.strip()
    if not target:
        return text, True
    raw = str(text)
    start = len(raw) - len(raw.lstrip())
    i = start
    j = 0
    while i < len(raw) and j < len(target):
        if raw[i].isspace():
            i += 1
            continue
        if target[j].isspace():
            j += 1
            continue
        if raw[i] != target[j]:
            return text, False
        i += 1
        j += 1
    while j < len(target) and target[j].isspace():
        j += 1
    if j != len(target):
        return text, False
    return raw[:start] + raw[i:], True


def _consume_content_prefix(contents, target):
    target_compact = re.sub(r"\s+", "", target)
    if not target_compact:
        return contents, True

    t = 0
    for idx, item in enumerate(contents):
        raw = str(item)
        pos = 0
        while pos < len(raw):
            if raw[pos].isspace():
                pos += 1
                continue
            if t >= len(target_compact):
                break
            if raw[pos] != target_compact[t]:
                return contents, False
            pos += 1
            t += 1
            if t == len(target_compact):
                while pos < len(raw) and raw[pos].isspace():
                    pos += 1
                if isinstance(item, TexNode):
                    if pos != len(raw):
                        return contents, False
                    return contents[idx + 1:], True
                updated = raw[pos:]
                rest = list(contents[idx + 1:])
                if updated.strip():
                    return [updated] + rest, True
                return rest, True
        if t == len(target_compact):
            return list(contents[idx + 1:]), True
    return contents, False


def table_body_contents(env_or_contents, args=None):
    """Return table contents with duplicated leading environment args removed."""
    if args is None and isinstance(env_or_contents, TexNode):
        try:
            args = list(env_or_contents.args)
        except Exception:
            args = []
        try:
            contents = list(env_or_contents.contents)
        except Exception:
            return []
    else:
        contents = list(env_or_contents)
        args = list(args or [])

    remaining = list(contents)
    for arg in args:
        target = _env_arg_body(arg)
        if not target:
            continue
        updated, matched = _consume_content_prefix(remaining, target)
        if matched:
            remaining = updated
            continue
        while remaining:
            first = remaining[0]
            if isinstance(first, TexNode):
                break
            updated, matched = _consume_text_prefix(str(first), target)
            if not matched:
                break
            if updated.strip():
                remaining[0] = updated
            else:
                remaining.pop(0)
            break
    while remaining:
        first = remaining[0]
        stripped = strip_leading_table_colspec(str(first))
        if stripped == str(first):
            break
        if stripped.strip():
            remaining[0] = stripped
            break
        remaining.pop(0)
    return remaining


def _balanced_group_end(text, pos, open_char, close_char):
    if pos >= len(text) or text[pos] != open_char:
        return None
    depth = 1
    i = pos + 1
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _table_command_at(text, pos):
    if not text.startswith("\\", pos):
        return None
    end = pos + 1
    if end >= len(text) or not (text[end].isalpha() or text[end] == "@"):
        return None
    end += 1
    while end < len(text) and (text[end].isalpha() or text[end] == "@"):
        end += 1
    if end < len(text) and text[end] == "*":
        end += 1
    return text[pos + 1:end], end


def _skip_optional_groups(text, pos):
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text) or text[pos] != "[":
            return pos
        end = _balanced_group_end(text, pos, "[", "]")
        if end is None:
            return pos
        pos = end


def _read_required_groups(text, pos, count):
    groups = []
    for _ in range(count):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text) or text[pos] != "{":
            return None
        end = _balanced_group_end(text, pos, "{", "}")
        if end is None:
            return None
        groups.append(text[pos + 1:end - 1])
        pos = end
    return groups, pos


def _image_placeholder(name):
    clean = str(name).replace("\\", "/").strip().lstrip("./")
    return "[image: %s]" % clean if clean else "[image]"


def _visible_wrapper_body(body):
    body = clean_table_fragment(body)
    body = re.sub(r"\\\\(?:\s*\[[^\]]*\])?", " ", body)
    return re.sub(r"\s+", " ", body).strip()


def clean_table_fragment(text):
    """Drop table layout TeX while preserving visible cell text."""
    out = []
    raw = str(text)
    i = 0
    while i < len(raw):
        if raw[i] == "{":
            end = _balanced_group_end(raw, i, "{", "}")
            if end is not None:
                inner = raw[i + 1:end - 1]
                if inner.lstrip().startswith((r"\color", r"\textcolor")):
                    out.append(clean_table_fragment(inner))
                    i = end
                    continue

        parsed = _table_command_at(raw, i)
        if parsed is None:
            out.append(raw[i])
            i += 1
            continue

        command, command_end = parsed
        low = command.lower().rstrip("*")
        pos = _skip_optional_groups(raw, command_end)

        if low in TABLE_SPACING_CMDS:
            out.append(" ")
            i = pos
            continue

        if low in {"begin", "end"}:
            parsed_env = _read_required_groups(raw, pos, 1)
            if parsed_env is not None:
                env_name = parsed_env[0][0].strip().lower()
                if env_name in TABLE_INNER_ENVS or env_name in {"longtable", "longtable*", "deluxetable", "deluxetable*"}:
                    i = parsed_env[1]
                    if low == "begin":
                        i = _skip_optional_groups(raw, i)
                        spec = _read_required_groups(raw, i, 1)
                        if spec is not None:
                            i = spec[1]
                    continue

        if low == "includegraphics":
            parsed_group = _read_required_groups(raw, pos, 1)
            if parsed_group is not None:
                out.append(_image_placeholder(parsed_group[0][0]))
                i = parsed_group[1]
                continue

        if low in TABLE_DROP_CMD_ARITY:
            count = TABLE_DROP_CMD_ARITY[low]
            parsed_groups = _read_required_groups(raw, pos, count) if count else ([], pos)
            if parsed_groups is not None:
                i = parsed_groups[1]
                continue

        if low == "color":
            parsed_group = _read_required_groups(raw, pos, 1)
            if parsed_group is not None:
                i = parsed_group[1]
                continue

        if low in TABLE_WRAPPER_CMD_ARITY:
            parsed_groups = _read_required_groups(raw, pos, TABLE_WRAPPER_CMD_ARITY[low])
            if parsed_groups is not None:
                out.append(_visible_wrapper_body(parsed_groups[0][-1]))
                i = parsed_groups[1]
                continue

        out.append(raw[i])
        i += 1
    return "".join(out)


def looks_like_table_colspec(spec):
    raw = str(spec).strip()
    if not raw:
        return False
    low = raw.lower()
    if "extracolsep" in low:
        return True
    if not any(ch in raw for ch in "lcrpmbxX"):
        return False
    scrubbed = re.sub(r"\\[A-Za-z@]+\*?", "", raw)
    scrubbed = re.sub(r"\{[^{}]*\}", "", scrubbed)
    scrubbed = re.sub(
        r"[-+]?\d+(?:\.\d+)?\s*(?:pt|em|ex|cm|mm|in|pc|bp|sp|\\(?:linewidth|textwidth|columnwidth))",
        "",
        scrubbed,
    )
    return not re.sub(r"[\s|@*<>{}!.,;:'\"()\[\]lcrpmbxX]", "", scrubbed)


def strip_leading_table_colspec(text):
    raw = str(text)
    while True:
        start = len(raw) - len(raw.lstrip())
        if start >= len(raw) or raw[start] != "{":
            return raw
        end = _balanced_group_end(raw, start, "{", "}")
        if end is None:
            return raw
        spec = raw[start + 1:end - 1]
        if not looks_like_table_colspec(spec):
            return raw
        raw = raw[:start] + raw[end:]

"""Source-level arXiv frontmatter extraction and cleanup.

The helpers in this module intentionally work on plain source strings. They
are small feature passes rather than parser-core behavior, which keeps the
interface straightforward to port to a future Rust implementation.
"""

from dataclasses import dataclass
import re

from TexSoup.scanner import (
    line_end as _line_end,
    parse_group as _parse_group,
    protected_spans as _protected_spans,
    read_control_sequence as _read_control_sequence,
    skip_spaces as _skip_spaces,
    starts_comment as _starts_comment,
)


@dataclass(frozen=True)
class FrontMatter:
    title: str = ""
    authors: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class FrontMatterSource:
    source: str
    frontmatter: FrontMatter


FRONTMATTER_COMMANDS = frozenset((
    "address",
    "affil",
    "affiliation",
    "altaffiliation",
    "author",
    "authorrunning",
    "conference",
    "cortext",
    "copyrightclause",
    "copyrightyear",
    "correspondingauthor",
    "date",
    "ead",
    "email",
    "fnmark",
    "fntext",
    "footnotemark",
    "footnotetext",
    "institute",
    "ieeekeywords",
    "keywords",
    "keyword",
    "maketitle",
    "orcid",
    "subtitle",
    "thanks",
    "title",
    "titlerunning",
))

_DROP_TEXT_COMMANDS = FRONTMATTER_COMMANDS | frozenset((
    "footnote",
    "footnotemark",
    "footnotetext",
))
_KEEP_CONTENT_COMMANDS = frozenset((
    "bf",
    "bfseries",
    "em",
    "emph",
    "it",
    "itshape",
    "large",
    "Large",
    "LARGE",
    "MakeUppercase",
    "normalfont",
    "normalsize",
    "rm",
    "rmfamily",
    "sc",
    "scshape",
    "small",
    "textbf",
    "textit",
    "textnormal",
    "textrm",
    "textsc",
    "textsf",
    "textsl",
    "uppercase",
))
_LAYOUT_COMMANDS = frozenset((
    "bigskip",
    "clearpage",
    "cleardoublepage",
    "hfill",
    "hskip",
    "hspace",
    "kern",
    "medskip",
    "newpage",
    "noindent",
    "pagebreak",
    "par",
    "smallskip",
    "spacingset",
    "thispagestyle",
    "vfill",
    "vskip",
    "vspace",
))
_SECTION_COMMANDS = frozenset((
    "part",
    "chapter",
    "section",
    "subsection",
    "subsubsection",
    "paragraph",
    "subparagraph",
))
_CONDITIONAL_COMMANDS = frozenset((
    "if",
    "ifcase",
    "ifcat",
    "ifdim",
    "ifeof",
    "iffalse",
    "ifhbox",
    "ifhmode",
    "ifinner",
    "ifmmode",
    "ifnum",
    "ifodd",
    "iftrue",
    "ifvbox",
    "ifvmode",
    "ifvoid",
    "ifx",
))
_KEYWORD_ENVIRONMENTS = ("keyword", "keywords", "IEEEkeywords")
_CLASSIFICATION_ENVIRONMENTS = ("MSC", "AMS", "PACS", "JEL", "subjclass")
_LAYOUT_ENVIRONMENTS = (
    "adjustwidth",
    "center",
    "flushleft",
    "flushright",
    "quote",
    "quotation",
)
_DOCUMENT_BEGIN_RE = re.compile(r"(?<!\\)\\begin\{document\}")
_DOCUMENT_END_RE = re.compile(r"(?<!\\)\\end\{document\}")
_DIGIT_MACRO_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand)\*?\s*"
    r"(?:\{\\(?P<braced>[A-Za-z@]+)\}|\\(?P<bare>[A-Za-z@]+))"
    r"\s*\{\s*(?P<digit>[01])\s*\}",
    re.DOTALL,
)


def standardize_frontmatter_source(tex):
    """Return source with frontmatter residue cleaned plus extracted metadata."""
    tex = evaluate_simple_conditionals(str(tex))
    frontmatter = extract_frontmatter(tex)
    return FrontMatterSource(clean_frontmatter_source(tex), frontmatter)


def extract_frontmatter(tex):
    """Extract compact title, authors, and keywords from common frontmatter."""
    tex = evaluate_simple_conditionals(str(tex))
    preamble, body, _suffix = _document_parts(tex)
    lead = _leading_document_source(body)
    zone = "%s\n%s" % (preamble, lead)

    title = _first_clean_command_text(zone, ("title",))
    if not title:
        title = _extract_center_title(lead)

    authors = _extract_ieee_author_blocks(zone)
    if not authors:
        authors = _clean_author_values(_command_texts(zone, ("author", "authors")))
    if not authors:
        author = _extract_centerline_author(lead)
        authors = (author,) if author else ()

    keywords = _extract_keywords(zone, lead)
    return FrontMatter(title=title, authors=authors, keywords=keywords)


def clean_frontmatter_source(tex):
    """Drop frontmatter and page-layout residue from the document body."""
    preamble, body, suffix = _document_parts(tex)
    if body is None:
        return _drop_frontmatter_command_spans(tex)

    body = _drop_keyword_environments(body)
    body = _clean_abstract_sources(body)
    section_pos = _find_first_command(body, _SECTION_COMMANDS)
    if section_pos is not None:
        lead = body[:section_pos]
        if _lead_has_frontmatter_signal(lead):
            lead = _clean_pre_section_frontmatter_lead(lead)
            body = lead + body[section_pos:]

    body = _drop_frontmatter_command_spans(body)
    return preamble + body + suffix


def evaluate_simple_conditionals(tex):
    """Evaluate simple ``\\if00`` / ``\\if0\\flag`` style source conditionals."""
    digit_macros = _collect_digit_macros(tex)
    for _ in range(4):
        updated, changed = _evaluate_simple_conditionals_once(tex, digit_macros)
        tex = updated
        if not changed:
            break
    return tex


def _document_parts(tex):
    begin = _DOCUMENT_BEGIN_RE.search(tex)
    if begin is None:
        return "", tex, ""
    end = _DOCUMENT_END_RE.search(tex, begin.end())
    body_end = end.start() if end is not None else len(tex)
    suffix = tex[body_end:] if end is not None else ""
    return tex[:begin.end()], tex[begin.end():body_end], suffix


def _collect_digit_macros(tex):
    out = {}
    for match in _DIGIT_MACRO_RE.finditer(tex):
        name = match.group("braced") or match.group("bare")
        if name:
            out[name] = match.group("digit")
    return out


def _evaluate_simple_conditionals_once(tex, digit_macros):
    spans = _protected_spans(tex)
    span_index = 0
    out = []
    changed = False
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
        if _starts_comment(tex, i):
            end = _line_end(tex, i)
            out.append(tex[i:end])
            i = end
            continue

        command, end = _read_control_sequence(tex, i)
        if command != r"\if":
            out.append(tex[i])
            i += 1
            continue

        left, pos = _read_conditional_token(tex, end, digit_macros)
        if left is None:
            out.append(tex[i])
            i += 1
            continue
        right, pos = _read_conditional_token(tex, pos, digit_macros)
        if right is None:
            out.append(tex[i])
            i += 1
            continue

        markers = _find_matching_conditional(tex, pos)
        if markers is None:
            out.append(tex[i])
            i += 1
            continue
        else_start, fi_start, fi_end = markers
        if left == right:
            chosen = tex[pos:(else_start if else_start is not None else fi_start)]
        else:
            chosen = tex[else_start + len(r"\else"):fi_start] if else_start is not None else ""
        out.append(chosen)
        i = fi_end
        changed = True

    return "".join(out), changed


def _read_conditional_token(tex, pos, digit_macros):
    pos = _skip_spaces(tex, pos)
    if pos < len(tex) and tex[pos] in "01":
        return tex[pos], pos + 1
    command, end = _read_control_sequence(tex, pos)
    if command:
        value = digit_macros.get(command[1:])
        if value is not None:
            return value, end
    return None, pos


def _find_matching_conditional(tex, pos):
    depth = 1
    else_start = None
    i = pos
    while i < len(tex):
        if _starts_comment(tex, i):
            i = _line_end(tex, i)
            continue
        command, end = _read_control_sequence(tex, i)
        if not command:
            i += 1
            continue
        name = command[1:]
        if name in _CONDITIONAL_COMMANDS:
            depth += 1
        elif name == "else" and depth == 1 and else_start is None:
            else_start = i
        elif name == "fi":
            depth -= 1
            if depth == 0:
                return else_start, i, end
        i = end
    return None


def _leading_document_source(body):
    if body is None:
        return ""
    pos = _find_first_command(body, _SECTION_COMMANDS)
    if pos is None:
        return body
    return body[:pos]


def _find_first_command(tex, names):
    spans = _protected_spans(tex)
    span_index = 0
    i = 0
    while i < len(tex):
        while span_index < len(spans) and i >= spans[span_index][1]:
            span_index += 1
        if span_index < len(spans) and spans[span_index][0] <= i:
            i = spans[span_index][1]
            span_index += 1
            continue
        if _starts_comment(tex, i):
            i = _line_end(tex, i)
            continue
        command, end = _read_control_sequence(tex, i)
        if command and command[1:].rstrip("*") in names:
            if command[1:].rstrip("*") in _SECTION_COMMANDS:
                section_span = _section_command_span(tex, end)
                if section_span is None:
                    i = end
                    continue
                if _is_empty_layout_section_command(tex, end):
                    i = section_span[1]
                    continue
            return i
        i = end if command else i + 1
    return None


def _section_command_span(tex, pos):
    pos = _skip_command_star_options(tex, pos)
    group = _parse_group(tex, pos, "{", "}")
    if group is None:
        return None
    return pos, group[1]


def _is_empty_layout_section_command(tex, pos):
    span = _section_command_span(tex, pos)
    if span is None:
        return False
    pos, _end = span
    group = _parse_group(tex, pos, "{", "}")
    return not _normalize_spaces(_clean_plain_text(group[0])).strip(" .;:-")


def _command_texts(tex, names):
    out = []
    for _name, body, _span in _iter_required_command_args(tex, names):
        text = _clean_plain_text(body)
        if text:
            out.append(text)
    return out


def _first_clean_command_text(tex, names):
    for text in _command_texts(tex, names):
        if _is_placeholder_title(text):
            continue
        return text
    return ""


def _iter_required_command_args(tex, names):
    spans = _protected_spans(tex)
    span_index = 0
    i = 0
    while i < len(tex):
        while span_index < len(spans) and i >= spans[span_index][1]:
            span_index += 1
        if span_index < len(spans) and spans[span_index][0] <= i:
            i = spans[span_index][1]
            span_index += 1
            continue
        if _starts_comment(tex, i):
            i = _line_end(tex, i)
            continue

        command, end = _read_control_sequence(tex, i)
        if not command:
            i += 1
            continue
        name = command[1:].rstrip("*")
        if name not in names:
            i = end
            continue
        pos = _skip_command_star_options(tex, end)
        group = _parse_group(tex, pos, "{", "}")
        if group is None:
            i = end
            continue
        yield name, group[0], (i, group[1])
        i = group[1]


def _skip_command_star_options(tex, pos):
    if pos < len(tex) and tex[pos] == "*":
        pos += 1
    while True:
        pos = _skip_spaces(tex, pos)
        group = _parse_group(tex, pos, "[", "]")
        if group is None:
            return pos
        pos = group[1]


def _extract_center_title(lead):
    for body, _span in _iter_environment_bodies(lead, ("center",)):
        if re.search(
            r"\\(?:begin\{(?:minipage|tabular|table|figure|picture|tikzpicture|"
            r"pgfpicture|pspicture|circuitikz|quantikz)\}|includegraphics)",
            body,
            re.IGNORECASE,
        ):
            continue
        text = _clean_plain_text(body)
        if text and not _is_placeholder_title(text):
            return text
    return ""


def _extract_centerline_author(lead):
    abstract_pos = _find_environment_begin(lead, "abstract")
    search = lead[:abstract_pos] if abstract_pos is not None else lead
    for _name, body, _span in _iter_required_command_args(search, ("centerline",)):
        text = _clean_author_text(body)
        if text:
            return text
    return ""


def _extract_keywords(zone, lead):
    values = []
    for body, _span in _iter_environment_bodies(zone, _KEYWORD_ENVIRONMENTS):
        values.extend(_split_keywords(body))
    for _name, body, _span in _iter_required_command_args(zone, ("keyword", "keywords")):
        values.extend(_split_keywords(body))
    for body, _span in _iter_environment_bodies(lead, ("abstract",)):
        values.extend(_extract_inline_keywords(body))
    for _name, body, _span in _iter_required_command_args(lead, ("abstract",)):
        values.extend(_extract_inline_keywords(body))
    values.extend(_extract_inline_keywords(lead))
    return _dedupe(values)


def _extract_inline_keywords(lead):
    lead = _remove_environment_spans(lead, ("abstract",))
    lead = _remove_environment_spans(lead, _KEYWORD_ENVIRONMENTS)
    pattern = re.compile(
        r"(?is)\bkeywords?\b\s*:?\s*(?P<body>.*?)(?="
        r"\\\\\s*\\\\|\\vfill|\\newpage|\\section|"
        r"\\noindent\s*\{[^{}]*(?:AMS|MSC|PACS|JEL)|$)"
    )
    out = []
    for match in pattern.finditer(lead):
        out.extend(_split_keywords(match.group("body")))
    return out


def _split_keywords(raw):
    text = _clean_plain_text(raw)
    text = re.sub(r"(?i)^keywords?\s*:\s*", "", text).strip()
    text = re.sub(r"(?i)\bieeekeywords\b", "", text)
    text = re.split(r"(?i)\b(?:AMS|MSC|PACS|JEL)\b", text, maxsplit=1)[0]
    text = text.replace("\\sep", ";")
    parts = re.split(r"\s*[;,]\s*", text)
    out = []
    for part in parts:
        part = _normalize_spaces(part).strip(" .;:-")
        if not part:
            continue
        if len(part) <= 1 and not any(ch.isalpha() for ch in part):
            continue
        if part.lower() in {"keywords", "keyword"}:
            continue
        out.append(part)
    return out


def _clean_author_values(values):
    out = []
    for value in values:
        text = _clean_author_text(value)
        if text:
            out.append(text)
    return tuple(_dedupe(out))


def _extract_ieee_author_blocks(tex):
    out = []
    for _name, body, _span in _iter_required_command_args(tex, ("IEEEauthorblockN",)):
        out.extend(_split_ieee_author_block(body))
    return tuple(_dedupe(out))


def _split_ieee_author_block(raw):
    raw = re.sub(r"\\\\", ";", str(raw))
    raw = re.sub(r"\\and\b", ";", raw)
    text = _clean_author_text(raw)
    text = re.sub(r"(?i)\s+\band\s+", ";", text)
    parts = re.split(r"\s*[;,]\s*", text)
    out = []
    for part in parts:
        part = _clean_ieee_author_name(part)
        if part:
            out.append(part)
    return out


def _clean_ieee_author_name(text):
    text = _normalize_spaces(text)
    text = re.sub(r"(?i)^\s*and\s+", "", text)
    text = re.sub(r"(?<![A-Za-z])(?:\d+|[*]+)(?![A-Za-z])", " ", text)
    text = re.sub(
        r"(?i)\b(?:graduate\s+student\s+member|student\s+member|"
        r"senior\s+member|life\s+fellow|fellow|member)\b",
        " ",
        text,
    )
    text = re.sub(r"(?i)\bieee\b", " ", text)
    text = _normalize_spaces(text).strip(" ,;:-")
    if not text or not any(ch.isalpha() for ch in text):
        return ""
    return text


def _clean_author_text(raw):
    text = _clean_plain_text(raw)
    text = re.sub(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", "", text)
    text = re.sub(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b", "", text)
    text = re.split(
        r"(?i)\b(?:affiliation|department|institute|university|e-?mail|"
        r"corresponding author|address)\b",
        text,
        maxsplit=1,
    )[0]
    text = re.sub(r"\s*\^\s*[\d*dagger]+\s*", " ", text)
    text = _normalize_spaces(text).strip(" ,;:-")
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text


def _clean_plain_text(raw):
    text = _strip_layout_environment_wrappers(str(raw))
    text = _flatten_latex_text(text)
    text = re.sub(r"(?i)\b(?:footnotesize|normalsize|small|large)\b", " ", text)
    text = re.sub(r"(?i)\b(?:vfill|vskip|newpage|noindent|bigskip|medskip|smallskip)\b", " ", text)
    return _normalize_spaces(text).strip(" \t\r\n{}[]")


def _strip_layout_environment_wrappers(raw):
    envs = "|".join(re.escape(name) for name in _LAYOUT_ENVIRONMENTS)
    text = re.sub(
        rf"\\begin\{{(?:{envs})\}}(?:\s*\{{[^{{}}]*\}})*",
        " ",
        raw,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"\\end\{{(?:{envs})\}}",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _flatten_latex_text(raw):
    text = str(raw).replace("~", " ")
    out = []
    i = 0
    while i < len(text):
        if _starts_comment(text, i):
            i = _line_end(text, i)
            continue
        char = text[i]
        if char == "\\":
            command, end = _read_control_sequence(text, i)
            if command:
                name = command[1:].rstrip("*")
                if command in (r"\\",):
                    out.append(" ")
                    i = end
                    continue
                if name in {"&", "%", "_", "#", "$", "{", "}"}:
                    out.append(name)
                    i = end
                    continue
                if name == "sep":
                    out.append("; ")
                    i = end
                    continue
                if name == "IEEEauthorrefmark" or "orcid" in name.lower():
                    i = _skip_command_span(text, end)
                    continue
                if name == "href":
                    kept, i = _flatten_second_required_arg(text, end)
                    out.append(kept)
                    continue
                if name in _DROP_TEXT_COMMANDS:
                    i = _skip_command_span(text, end)
                    continue
                if name in _LAYOUT_COMMANDS:
                    i = _skip_layout_command_span(text, name, end)
                    continue
                pos = _skip_command_star_options(text, end)
                group = _parse_group(text, pos, "{", "}")
                if group is not None:
                    out.append(_flatten_latex_text(group[0]))
                    i = group[1]
                    continue
                if name in _KEEP_CONTENT_COMMANDS:
                    i = end
                    continue
                i = end
                continue
            if i + 1 < len(text) and text[i + 1] in r"&%_#${}":
                out.append(text[i + 1])
                i += 2
                continue
        if char in "{}$":
            out.append(" ")
        elif char in "[]":
            out.append(" ")
        else:
            out.append(char)
        i += 1
    return _normalize_spaces("".join(out))


def _flatten_second_required_arg(text, pos):
    pos = _skip_command_star_options(text, pos)
    first = _parse_group(text, pos, "{", "}")
    if first is None:
        return "", pos
    pos = _skip_spaces(text, first[1])
    second = _parse_group(text, pos, "{", "}")
    if second is None:
        return _flatten_latex_text(first[0]), first[1]
    return _flatten_latex_text(second[0]), second[1]


def _skip_command_span(text, pos, max_groups=3):
    pos = _skip_command_star_options(text, pos)
    groups = 0
    while groups < max_groups:
        group = _parse_group(text, pos, "{", "}")
        if group is None:
            break
        pos = _skip_spaces(text, group[1])
        groups += 1
    while True:
        group = _parse_group(text, pos, "[", "]")
        if group is None:
            return pos
        pos = _skip_spaces(text, group[1])


def _drop_frontmatter_command_spans(body):
    spans = []
    for _name, _raw, span in _iter_frontmatter_command_spans(body):
        spans.append(span)
    return _replace_spans(body, spans, " ")


def _iter_frontmatter_command_spans(tex):
    spans = _protected_spans(tex)
    span_index = 0
    i = 0
    while i < len(tex):
        while span_index < len(spans) and i >= spans[span_index][1]:
            span_index += 1
        if span_index < len(spans) and spans[span_index][0] <= i:
            i = spans[span_index][1]
            span_index += 1
            continue
        if _starts_comment(tex, i):
            i = _line_end(tex, i)
            continue
        command, end = _read_control_sequence(tex, i)
        if not command:
            i += 1
            continue
        name = command[1:].rstrip("*")
        if name not in FRONTMATTER_COMMANDS:
            i = end
            continue
        span_end = _skip_command_span(tex, end)
        yield name, tex[i:span_end], (i, span_end)
        i = span_end


def _drop_keyword_environments(body):
    spans = [span for _body, span in _iter_environment_bodies(body, _KEYWORD_ENVIRONMENTS)]
    return _replace_spans(body, spans, " ")


def _drop_classification_environments(body):
    spans = [
        span
        for _body, span in _iter_environment_bodies(body, _CLASSIFICATION_ENVIRONMENTS)
    ]
    return _replace_spans(body, spans, " ")


def _clean_abstract_sources(tex):
    replacements = []
    for body, (start, end) in _iter_environment_bodies(tex, ("abstract",)):
        cleaned = _clean_abstract_body(body).strip()
        replacements.append((start, end, "\\begin{abstract}\n" + cleaned + "\n\\end{abstract}"))
    for _name, body, (start, end) in _iter_required_command_args(tex, ("abstract",)):
        cleaned = _clean_abstract_body(body).strip()
        replacements.append((start, end, "\\abstract{" + cleaned + "}"))
    if not replacements:
        return tex
    parts = []
    last = len(tex)
    for start, end, replacement in sorted(replacements, reverse=True):
        parts.append(tex[end:last])
        parts.append(replacement)
        last = start
    parts.append(tex[:last])
    return "".join(reversed(parts))


def _kept_abstract_sources(lead):
    kept = [
        "\\begin{abstract}\n" + _clean_abstract_body(body).strip() + "\n\\end{abstract}"
        for body, _span in _iter_environment_bodies(lead, ("abstract",))
    ]
    for _name, body, _span in _iter_required_command_args(lead, ("abstract",)):
        kept.append("\\abstract{" + _clean_abstract_body(body).strip() + "}")
    return [item for item in kept if item]


def _clean_abstract_body(body):
    body = _drop_keyword_environments(body)
    body = _drop_classification_environments(body)
    body = _drop_inline_keyword_blocks(body)
    body = _drop_inline_classification_blocks(body)
    return body


def _clean_pre_section_frontmatter_lead(lead):
    maketitle_end = _first_frontmatter_command_span_end(lead, "maketitle")
    if maketitle_end is not None:
        rest = lead[maketitle_end:]
        kept = _kept_abstract_sources(lead)
        bodyish = _remove_environment_spans(rest, ("abstract",))
        bodyish = _drop_keyword_environments(bodyish)
        bodyish = _drop_classification_environments(bodyish)
        bodyish = _drop_inline_keyword_blocks(bodyish)
        bodyish = _drop_inline_classification_blocks(bodyish)
        bodyish = _drop_frontmatter_command_spans(bodyish)
        bodyish = _drop_layout_command_spans(bodyish)
        if not _has_bodyish_lead_content(bodyish):
            bodyish = ""
        parts = [item for item in (*kept, bodyish.strip()) if item]
        return ("\n".join(parts) + "\n") if parts else "\n"
    kept = _kept_abstract_sources(lead)
    bodyish = _remove_environment_spans(lead, ("abstract",))
    bodyish = _drop_keyword_environments(bodyish)
    bodyish = _drop_classification_environments(bodyish)
    bodyish = _drop_inline_keyword_blocks(bodyish)
    bodyish = _drop_inline_classification_blocks(bodyish)
    bodyish = _drop_frontmatter_command_spans(bodyish)
    bodyish = _drop_layout_command_spans(bodyish)
    if kept or _lead_has_strong_frontmatter_signal(lead):
        return ("\n".join(kept) + "\n") if kept else "\n"
    if _has_bodyish_lead_content(bodyish):
        return bodyish.strip() + "\n"
    return "\n"


def _first_frontmatter_command_span_end(tex, command_name):
    for name, _raw, (_start, end) in _iter_frontmatter_command_spans(tex):
        if name == command_name:
            return end
    return None


def _drop_inline_keyword_blocks(tex):
    pattern = re.compile(
        r"(?is)(?:\\noindent\s*%?\s*)?"
        r"(?:\{\\(?:it|bf|em|small|footnotesize)\s*\{?\s*)?"
        r"(?:\\(?:textbf|emph)\{)?\s*\bkeywords?\b\s*:.*?"
        r"(?:\}\s*){0,2}"
        r"(?=\\vfill|\\newpage|\\clearpage|\\spacingset|\\bigskip|$)"
    )
    return pattern.sub(" ", tex)


def _drop_inline_classification_blocks(tex):
    pattern = re.compile(
        r"(?im)^\s*(?:%\s*)?"
        r"(?:JEL\s+(?:Code|Classification)|"
        r"AMS\s+(?:Subject\s+)?Classification(?:\s+Numbers?)?|"
        r"MSC\s+Classification|"
        r"Mathematics\s+Subject\s+Classification|"
        r"PACS(?:\s+(?:numbers?|codes?))?)"
        r"\s*:?.*$"
    )
    return pattern.sub(" ", tex)


def _drop_layout_command_spans(tex):
    spans = []
    for _name, span in _iter_command_spans(tex, _LAYOUT_COMMANDS):
        spans.append(span)
    return _replace_spans(tex, spans, " ")


_DIMENSION_SKIP_RE = re.compile(
    r"\s*-?\d+(?:\.\d+)?\s*(?:pt|em|ex|cm|mm|in|mu|sp|fil|fill|baselineskip)"
    r"(?:\s+plus\s+-?\d+(?:\.\d+)?\s*(?:pt|em|ex|cm|mm|in|mu|sp|fil|fill|baselineskip))?"
    r"(?:\s+minus\s+-?\d+(?:\.\d+)?\s*(?:pt|em|ex|cm|mm|in|mu|sp|fil|fill|baselineskip))?",
    re.IGNORECASE,
)


def _skip_layout_command_span(text, name, pos):
    if name in {"hskip", "vskip", "kern"}:
        match = _DIMENSION_SKIP_RE.match(text, pos)
        if match is not None:
            return match.end()
    return _skip_command_span(text, pos)


def _iter_command_spans(tex, names):
    spans = _protected_spans(tex)
    span_index = 0
    i = 0
    while i < len(tex):
        while span_index < len(spans) and i >= spans[span_index][1]:
            span_index += 1
        if span_index < len(spans) and spans[span_index][0] <= i:
            i = spans[span_index][1]
            span_index += 1
            continue
        if _starts_comment(tex, i):
            i = _line_end(tex, i)
            continue
        command, end = _read_control_sequence(tex, i)
        if not command:
            i += 1
            continue
        name = command[1:].rstrip("*")
        if name not in names:
            i = end
            continue
        span_end = _skip_layout_command_span(tex, name, end)
        yield name, (i, span_end)
        i = span_end


def _has_bodyish_lead_content(tex):
    if re.search(r"\\begin\{(?:figure|figure\*|table|table\*|equation|align)\}", tex):
        return True
    text = _clean_plain_text(tex)
    text = re.sub(r"(?i)\b(?:noindent|vfill|newpage|spacingset)\b", " ", text)
    text = _normalize_spaces(text).strip(" .;:-")
    return len(text) >= 20


def _has_keyword_token(text):
    return re.search(r"(?i)\bkeywords?\b", text) is not None


def _lead_has_frontmatter_signal(lead):
    low = lead.lower()
    return (
        r"\maketitle" in lead
        or r"\twocolumn[" in lead
        or r"\begin{abstract}" in low
        or r"\title" in low
        or r"\author" in low
        or _has_keyword_token(lead)
        or "affiliation" in low
        or "e-mail" in low
        or "email" in low
        or r"\centerline" in low
        or r"\begin{center}" in low
        or "head_foot/" in low
        or "journal_name" in low
        or "header_bar" in low
    )


def _lead_has_strong_frontmatter_signal(lead):
    low = lead.lower()
    return (
        r"\maketitle" in lead
        or r"\twocolumn[" in lead
        or r"\title" in low
        or r"\author" in low
        or _has_keyword_token(lead)
        or "affiliation" in low
        or "e-mail" in low
        or "email" in low
        or r"\centerline" in low
        or "head_foot/" in low
        or "journal_name" in low
        or "header_bar" in low
    )


def _iter_environment_bodies(tex, names):
    for name in names:
        pattern = re.compile(
            r"\\begin\{" + re.escape(name) + r"\}(?P<body>.*?)"
            r"\\end\{" + re.escape(name) + r"\}",
            re.DOTALL | re.IGNORECASE,
        )
        for match in pattern.finditer(tex):
            yield match.group("body"), (match.start(), match.end())


def _remove_environment_spans(tex, names):
    spans = [span for _body, span in _iter_environment_bodies(tex, names)]
    return _replace_spans(tex, spans, " ")


def _find_environment_begin(tex, name):
    match = re.search(r"\\begin\{" + re.escape(name) + r"\}", tex, re.IGNORECASE)
    return match.start() if match else None


def _replace_spans(tex, spans, replacement):
    if not spans:
        return tex
    out = []
    cursor = 0
    for start, end in _merge_spans(spans):
        out.append(tex[cursor:start])
        out.append(replacement)
        cursor = end
    out.append(tex[cursor:])
    return "".join(out)


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


def _dedupe(values):
    out = []
    seen = set()
    for value in values:
        value = _normalize_spaces(value).strip(" ,;:")
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return tuple(out)


def _normalize_spaces(text):
    return re.sub(r"\s+", " ", str(text)).strip()


def _is_placeholder_title(text):
    low = _normalize_spaces(text).strip(" .:").lower()
    return low in {"title", "paper title", "article title"} or low.isdigit()

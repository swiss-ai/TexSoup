"""TeX source preparation.

These helpers intentionally stay outside the parser core. They turn a local
or in-memory paper source tree into one TeX string by selecting a main file,
expanding common input commands, and optionally inlining compiled bibliography
files. Keeping the logic here gives the Rust rewrite a small, deterministic
feature pass to match before it is wired into the public parser.
"""

from collections.abc import Mapping
import csv
import io
import re
from pathlib import Path, PurePosixPath

from TexSoup.macros import Macro
from TexSoup.macros import collect_simple_macros
from TexSoup.macros import expand_macro_uses
from TexSoup.scanner import line_end as scan_line_end
from TexSoup.scanner import protected_spans as scan_protected_spans
from TexSoup.scanner import starts_comment as starts_line_comment
from TexSoup.tables import clean_table_fragment


SUPPORTED_TEX_SUFFIXES = ('.tex', '.ltx')
TEXTY_TEX_SUFFIXES = SUPPORTED_TEX_SUFFIXES + ('.sty', '.cls')
INPUT_COMMANDS = frozenset(('subimport', 'import', 'include', 'input', 'subfile'))
LISTING_INPUT_COMMANDS = frozenset(('lstinputlisting', 'inputminted'))
BIBLIOGRAPHY_SOURCE_COMMANDS = frozenset(('bibliography', 'addbibresource'))
BIBLIOGRAPHY_REPLACEMENT_COMMANDS = frozenset(
    ('bibliography', 'printbibliography')
)
PGFPLOTSTABLE_COMMANDS = frozenset(('pgfplotstabletypeset',))
FILE_CONDITIONAL_COMMANDS = frozenset(('IfFileExists',))
DOCUMENTCLASS_RE = re.compile(
    r'\\documentclass(?:\s*\[[^\[\]]*\])?\s*\{[^{}]*\}'
)
BEGIN_DOCUMENT_RE = re.compile(r'\\begin\s*\{document\}')
END_DOCUMENT_RE = re.compile(r'\\end\s*\{document\}')
CSV_VISIBLE_TEXT_WRAPPER_ARITY = {
    'emph': 1,
    'mbox': 1,
    'textrm': 1,
    'textbf': 1,
    'textit': 1,
    'textmd': 1,
    'textnormal': 1,
    'textsc': 1,
    'textsf': 1,
    'textsl': 1,
    'texttt': 1,
    'textup': 1,
    'underline': 1,
    'colorbox': 2,
    'fcolorbox': 3,
    'textcolor': 2,
}
CSV_ESCAPED_TEXT_CHAR_RE = re.compile(r'\\([#%&_])')


def _coerce_source_text(value):
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='ignore')
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_memory_path(path):
    raw = str(path).replace('\\', '/')
    parts = []
    for part in raw.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            if parts and parts[-1] != '..':
                parts.pop()
            else:
                parts.append(part)
            continue
        parts.append(part)
    return '/'.join(parts)


def _memory_join(base_dir, raw_path):
    raw_path = str(raw_path).replace('\\', '/')
    if raw_path.startswith('/'):
        return _normalize_memory_path(raw_path)
    base_dir = _normalize_memory_path(base_dir)
    if not base_dir:
        return _normalize_memory_path(raw_path)
    return _normalize_memory_path('%s/%s' % (base_dir, raw_path))


def _path_name(path):
    raw = str(path).replace('\\', '/').rstrip('/')
    return raw.rsplit('/', 1)[-1]


def _allow_case_insensitive_target_fallback(raw_target):
    name = _path_name(raw_target)
    stem = PurePosixPath(name.replace('\\', '/')).stem or name
    return any(char.isupper() for char in stem)


def _main_score(path, text):
    lower_name = _path_name(path).lower()
    score = 0
    if lower_name in (
        'main.tex',
        'paper.tex',
        'article.tex',
        'ms.tex',
        'manuscript.tex',
    ):
        score += 400
    if r'\begin{document}' in text:
        score += 2000
    if r'\documentclass' in text:
        score += 700
    if r'\title' in text:
        score += 100
    if r'\begin{abstract}' in text or r'\abstract' in text:
        score += 100
    score += min(len(text), 1000000) // 20000
    return score


class InMemoryTexSource:
    """Path-keyed in-memory TeX package.

    Paths are normalized as package-relative POSIX-style strings. Values may be
    ``str`` or UTF-8 ``bytes``; bytes use the same ``errors='ignore'`` policy as
    filesystem reads.
    """

    def __init__(self, files):
        self.files = {}
        for path, text in files.items():
            self.files[self.normalize_path(path)] = _coerce_source_text(text)

    def normalize_path(self, path):
        return _normalize_memory_path(path)

    def iter_files(self):
        return sorted(self.files)

    def is_file(self, path):
        return self.normalize_path(path) in self.files

    def read_text(self, path):
        return self.files[self.normalize_path(path)]

    def parent(self, path):
        path = self.normalize_path(path)
        if '/' not in path:
            return ''
        return path.rsplit('/', 1)[0]

    def join(self, base_dir, raw_path):
        return _memory_join(base_dir, raw_path)

    def suffix(self, path):
        return PurePosixPath(self.normalize_path(path)).suffix.lower()

    def with_suffix(self, path, suffix):
        path = PurePosixPath(self.normalize_path(path))
        return self.normalize_path(path.with_suffix(suffix))

    def resolve_target(self, base_dir, raw_target):
        raw_target = raw_target.strip()
        if not raw_target:
            return None
        raw_path = PurePosixPath(raw_target.replace('\\', '/'))
        candidates = [self.join(base_dir, raw_target)]
        if raw_path.suffix.lower() not in SUPPORTED_TEX_SUFFIXES:
            candidates.append(self.join(base_dir, '%s.tex' % raw_target))
        root_target = self.normalize_path(raw_target)
        if root_target not in candidates:
            candidates.append(root_target)
            if PurePosixPath(root_target).suffix.lower() not in SUPPORTED_TEX_SUFFIXES:
                candidates.append('%s.tex' % root_target)
        for candidate in candidates:
            if self.is_file(candidate):
                return self.normalize_path(candidate)
        if _allow_case_insensitive_target_fallback(raw_target):
            lower_candidates = {
                self.normalize_path(candidate).lower()
                for candidate in candidates
            }
            matches = [
                path for path in self.iter_files()
                if path.lower() in lower_candidates
            ]
            if len(matches) == 1:
                return matches[0]
        suffixes = tuple('/%s' % candidate for candidate in candidates)
        matches = [
            path for path in self.iter_files()
            if any(path.endswith(suffix) for suffix in suffixes)
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def glob_suffix(self, base_dir, suffix):
        base_dir = self.normalize_path(base_dir)
        prefix = '%s/' % base_dir if base_dir else ''
        matches = []
        for path in self.iter_files():
            if not path.startswith(prefix):
                continue
            relative = path[len(prefix):]
            if '/' not in relative and self.suffix(path) == suffix:
                matches.append(path)
        return matches


class _FilesystemTexSource:
    def normalize_path(self, path):
        return Path(path).resolve()

    def iter_files(self):
        raise TypeError('filesystem roots must be listed with iter_tex_files(root)')

    def is_file(self, path):
        return Path(path).is_file()

    def read_text(self, path):
        return read_text(path)

    def parent(self, path):
        return Path(path).parent

    def join(self, base_dir, raw_path):
        return Path(base_dir) / raw_path

    def suffix(self, path):
        return Path(path).suffix.lower()

    def with_suffix(self, path, suffix):
        return Path(path).with_suffix(suffix)

    def resolve_target(self, base_dir, raw_target):
        return resolve_target(base_dir, raw_target)

    def glob_suffix(self, base_dir, suffix):
        return sorted(Path(base_dir).glob('*%s' % suffix))


def _coerce_source(source):
    if isinstance(source, InMemoryTexSource):
        return source
    if isinstance(source, Mapping):
        return InMemoryTexSource(source)
    required = (
        'glob_suffix',
        'is_file',
        'join',
        'normalize_path',
        'parent',
        'read_text',
        'resolve_target',
        'suffix',
        'with_suffix',
    )
    missing = [name for name in required if not hasattr(source, name)]
    if missing:
        raise TypeError(
            'source must be a mapping or source object; missing %s'
            % ', '.join(missing)
        )
    return source


def read_text(path):
    return Path(path).read_text(encoding='utf-8', errors='ignore')


def iter_tex_files(root):
    root = Path(root)
    return [
        path for path in sorted(root.rglob('*'))
        if path.is_file() and path.suffix.lower() in SUPPORTED_TEX_SUFFIXES
    ]


def pick_main_tex(root):
    candidates = []
    for path in iter_tex_files(root):
        text = read_text(path)
        candidates.append((_main_score(path, text), path))
    if not candidates:
        raise RuntimeError('No TeX source files found under %s' % root)
    return max(candidates, key=lambda item: item[0])[1]


def iter_tex_source_files(source):
    source = _coerce_source(source)
    return [
        path for path in source.iter_files()
        if source.suffix(path) in SUPPORTED_TEX_SUFFIXES
    ]


def pick_main_source(source):
    source = _coerce_source(source)
    candidates = []
    for path in iter_tex_source_files(source):
        candidates.append((_main_score(path, source.read_text(path)), path))
    if not candidates:
        raise RuntimeError('No TeX source files found in source package')
    return max(candidates, key=lambda item: item[0])[1]


def scan_command(text, pos):
    if pos >= len(text) or text[pos] != '\\' or pos + 1 >= len(text):
        return None, pos
    if text[pos + 1].isalpha() or text[pos + 1] == '@':
        end = pos + 2
        while end < len(text) and (text[end].isalpha() or text[end] == '@'):
            end += 1
        if end < len(text) and text[end] == '*':
            end += 1
        return text[pos + 1:end], end
    return text[pos + 1:pos + 2], pos + 2


def skip_scanner_space_and_comments(text, pos):
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        if starts_line_comment(text, pos):
            pos = scan_line_end(text, pos)
            continue
        break
    return pos


def scan_bare_argument(text, pos):
    if pos >= len(text) or text[pos] in '{}[]%':
        return None
    start = pos
    while pos < len(text):
        if text[pos].isspace() or text[pos] in '{}[]%':
            break
        pos += 1
    if pos == start:
        return None
    return text[start:pos], pos


def scan_balanced_group(text, pos, open_char, close_char):
    if pos >= len(text) or text[pos] != open_char:
        return None
    depth = 1
    i = pos + 1
    while i < len(text):
        if text[i] == '\\':
            i += 2
            continue
        if starts_line_comment(text, i):
            i = scan_line_end(text, i)
            continue
        if text[i] == open_char:
            depth += 1
        elif text[i] == close_char:
            depth -= 1
            if depth == 0:
                return text[pos + 1:i], i + 1
        i += 1
    return None


def scan_command_calls(text, names):
    names = set(names)
    i = 0
    while i < len(text):
        if starts_line_comment(text, i):
            i = scan_line_end(text, i)
            continue
        name, end = scan_command(text, i)
        if name is None:
            i += 1
            continue

        base_name = name[:-1] if name.endswith('*') else name
        if name not in names and base_name not in names:
            i = end
            continue

        pos = skip_scanner_space_and_comments(text, end)
        call_end = end
        optional_args = []
        while True:
            optional = scan_balanced_group(text, pos, '[', ']')
            if optional is None:
                break
            optional_args.append(optional[0])
            call_end = optional[1]
            pos = skip_scanner_space_and_comments(text, optional[1])

        required_args = []
        while True:
            group = scan_balanced_group(text, pos, '{', '}')
            if group is None:
                break
            required_args.append(group[0])
            call_end = group[1]
            pos = skip_scanner_space_and_comments(text, group[1])

        bare_arg = None
        if not required_args:
            bare = scan_bare_argument(text, pos)
            if bare is not None:
                bare_arg, call_end = bare

        yield {
            'name': name,
            'base_name': base_name,
            'start': i,
            'end': call_end,
            'optional_args': optional_args,
            'required_args': required_args,
            'bare_arg': bare_arg,
        }
        i = call_end


def replace_spans(text, replacements):
    pieces = []
    cursor = 0
    for start, end, replacement in sorted(replacements):
        if start < cursor:
            continue
        pieces.append(text[cursor:start])
        pieces.append(replacement)
        cursor = end
    pieces.append(text[cursor:])
    return ''.join(pieces)


def _source_has_file(source, base_dir, raw_target):
    raw_target = str(raw_target).strip()
    if not raw_target:
        return False
    candidates = [
        source.join(base_dir, raw_target),
        source.normalize_path(raw_target),
    ]
    for candidate in candidates:
        try:
            if source.is_file(candidate):
                return True
        except Exception:
            continue
    if hasattr(source, 'iter_files'):
        lowered = set()
        for candidate in candidates:
            try:
                lowered.add(source.normalize_path(candidate).lower())
            except Exception:
                lowered.add(str(candidate).replace('\\', '/').lower())
        try:
            return any(path.lower() in lowered for path in source.iter_files())
        except Exception:
            return False
    return False


def _expand_file_conditionals(source, path, text):
    base_dir = source.parent(path)
    replacements = []
    for call in scan_command_calls(text, FILE_CONDITIONAL_COMMANDS):
        if len(call['required_args']) < 3:
            continue
        target, present, missing = call['required_args'][:3]
        replacement = present if _source_has_file(source, base_dir, target) else missing
        replacements.append((call['start'], call['end'], replacement))
    if not replacements:
        return text
    return replace_spans(text, replacements)


def _simple_let_aliases(text):
    aliases = {}
    replacements = []
    protected = scan_protected_spans(text)
    protected_index = 0
    i = 0
    while i < len(text):
        while protected_index < len(protected) and i >= protected[protected_index][1]:
            protected_index += 1
        if protected_index < len(protected) and protected[protected_index][0] <= i:
            i = protected[protected_index][1]
            continue
        if starts_line_comment(text, i):
            i = scan_line_end(text, i)
            continue

        name, end = scan_command(text, i)
        if name != 'let':
            i += 1
            continue
        pos = skip_scanner_space_and_comments(text, end)
        alias, alias_end = scan_command(text, pos)
        if not alias:
            i = end
            continue
        pos = skip_scanner_space_and_comments(text, alias_end)
        if pos < len(text) and text[pos] == '=':
            pos = skip_scanner_space_and_comments(text, pos + 1)
        target, target_end = scan_command(text, pos)
        if not target:
            i = alias_end
            continue
        aliases['\\' + alias] = '\\' + target
        replacements.append((i, target_end, ''))
        i = target_end
    return aliases, replacements


def _expand_simple_let_aliases(text):
    aliases, replacements = _simple_let_aliases(text)
    if not aliases:
        return text
    stripped = replace_spans(text, replacements)
    macros = {
        alias: Macro(alias, 0, target)
        for alias, target in aliases.items()
    }
    return expand_macro_uses(stripped, macros, [])


def _data_target_candidates(source, base_dir, raw_target, suffix):
    raw_target = str(raw_target).strip().strip('"\'')
    if not raw_target:
        return []
    raw_path = PurePosixPath(raw_target.replace('\\', '/'))
    candidates = [source.join(base_dir, raw_target)]
    if raw_path.suffix.lower() != suffix:
        candidates.append(source.join(base_dir, '%s%s' % (raw_target, suffix)))
    root_target = source.normalize_path(raw_target)
    candidates.append(root_target)
    if PurePosixPath(str(root_target)).suffix.lower() != suffix:
        candidates.append(source.normalize_path('%s%s' % (raw_target, suffix)))

    seen = set()
    out = []
    for candidate in candidates:
        normalized = source.normalize_path(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _resolve_data_target(source, base_dir, raw_target, suffix):
    candidates = _data_target_candidates(source, base_dir, raw_target, suffix)
    for candidate in candidates:
        if source.is_file(candidate):
            return candidate

    if hasattr(source, 'iter_files'):
        wanted = {
            str(candidate).replace('\\', '/').lower()
            for candidate in candidates
        }
        names = {
            _path_name(candidate).lower()
            for candidate in candidates
        }
        matches = [
            path for path in source.iter_files()
            if (
                str(path).replace('\\', '/').lower() in wanted
                or _path_name(path).lower() in names
            )
        ]
        matches = [path for path in matches if source.suffix(path) == suffix]
        if len(matches) == 1:
            return source.normalize_path(matches[0])
    return None


def _csv_rows_from_source(source, base_dir, raw_target):
    target = _resolve_data_target(source, base_dir, raw_target, '.csv')
    if target is None:
        return None
    text = source.read_text(target)
    return [
        row for row in csv.reader(io.StringIO(text))
        if any(str(cell).strip() for cell in row)
    ]


def _strip_balanced_outer_group(text):
    text = str(text).strip()
    while text.startswith('{') and text.endswith('}'):
        group = scan_balanced_group(text, 0, '{', '}')
        if group is None or group[1] != len(text):
            break
        text = group[0].strip()
    return text


def _csv_macro_body_is_visible_argument(body):
    text = _strip_balanced_outer_group(body)
    if text == '#1':
        return True

    command, pos = scan_command(text, 0)
    if command is None:
        return False
    command = command.rstrip('*')
    arity = CSV_VISIBLE_TEXT_WRAPPER_ARITY.get(command)
    if arity is None:
        return False

    pos = skip_scanner_space_and_comments(text, pos)
    while True:
        optional = scan_balanced_group(text, pos, '[', ']')
        if optional is None:
            break
        pos = skip_scanner_space_and_comments(text, optional[1])

    groups = []
    for _ in range(arity):
        group = scan_balanced_group(text, pos, '{', '}')
        if group is None:
            return False
        groups.append(group[0])
        pos = skip_scanner_space_and_comments(text, group[1])
    if text[pos:].strip():
        return False
    return _csv_macro_body_is_visible_argument(groups[-1])


def _iter_csv_macro_source_chunks(tex, source):
    yield str(tex)
    if not hasattr(source, 'iter_files'):
        return
    for path in source.iter_files():
        if source.suffix(path) not in TEXTY_TEX_SUFFIXES:
            continue
        try:
            chunk = source.read_text(path)
        except Exception:
            continue
        if chunk:
            yield chunk


def _csv_visible_text_macros(tex, source):
    macros = {}
    for chunk in _iter_csv_macro_source_chunks(tex, source):
        found, _ = collect_simple_macros(str(chunk))
        for name, macro in found.items():
            if macro.nargs != 1 or macro.optional_default is not None:
                continue
            if not _csv_macro_body_is_visible_argument(macro.body):
                continue
            macros[name] = Macro(name, 1, '#1')
    return macros


def _csv_text_cell(value, text_macros):
    text = str(value)
    if text_macros:
        text = expand_macro_uses(text, text_macros, [])
    if '\\' in text or '{' in text:
        text = clean_table_fragment(text)
    return CSV_ESCAPED_TEXT_CHAR_RE.sub(r'\1', text)


def _csv_cell_latex(value, text_macros=None):
    value = _csv_text_cell(value, text_macros)
    return (
        str(value)
        .replace('\\', r'\textbackslash{}')
        .replace('&', r'\&')
        .replace('%', r'\%')
        .replace('_', r'\_')
        .replace('#', r'\#')
    )


def _render_csv_tabular(rows, text_macros=None):
    if not rows:
        return ''
    cols = max(len(row) for row in rows)
    spec = 'l' * cols
    lines = []
    for row in rows:
        padded = [*row, *([""] * (cols - len(row)))]
        lines.append(
            ' & '.join(_csv_cell_latex(value, text_macros) for value in padded)
        )
    return (
        '\\begin{tabular}{%s}\n' % spec
        + '\\\\\n'.join(lines)
        + '\\\\\n'
        + '\\end{tabular}\n'
    )


def expand_pgfplotstabletypeset(tex, source, base_dir=''):
    """Expand simple local CSV-backed ``\\pgfplotstabletypeset`` calls.

    Unknown table macros and unresolved files are left unchanged. This pass is
    intentionally conservative: it only exposes locally redistributed CSV data
    as a plain tabular for downstream table normalization.
    """
    source = _coerce_source(source)
    replacements = []
    text_macros = None
    for call in scan_command_calls(str(tex), PGFPLOTSTABLE_COMMANDS):
        raw_target = None
        if call['required_args']:
            raw_target = call['required_args'][-1]
        elif call.get('bare_arg'):
            raw_target = call['bare_arg']
        if raw_target is None:
            continue
        rows = _csv_rows_from_source(source, base_dir, raw_target)
        if rows is None:
            continue
        if text_macros is None:
            text_macros = _csv_visible_text_macros(tex, source)
        replacements.append((
            call['start'],
            call['end'],
            _render_csv_tabular(rows, text_macros),
        ))
    if not replacements:
        return tex
    return replace_spans(str(tex), replacements)


def resolve_target(base_dir, raw_target):
    raw_target = raw_target.strip()
    if not raw_target:
        return None
    base_dir = Path(base_dir)
    raw_path = PurePosixPath(raw_target.replace('\\', '/'))
    candidates = [base_dir / raw_target]
    if raw_path.suffix.lower() not in SUPPORTED_TEX_SUFFIXES:
        candidates.append(base_dir / ('%s.tex' % raw_target))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def bibliography_stems(text):
    stems = []
    for call in scan_command_calls(text, BIBLIOGRAPHY_SOURCE_COMMANDS):
        for raw_arg in call['required_args']:
            for raw_name in raw_arg.split(','):
                raw_name = raw_name.strip()
                if raw_name:
                    path = PurePosixPath(raw_name.replace('\\', '/'))
                    stems.append(path.stem)
    return stems


def _load_bibliography_text(source, current_file, text, visited, allow_fallback=True):
    current_file = source.normalize_path(current_file)
    current_dir = source.parent(current_file)
    candidates = []
    for call in scan_command_calls(text, BIBLIOGRAPHY_SOURCE_COMMANDS):
        for raw_arg in call['required_args']:
            for raw_name in raw_arg.split(','):
                raw_name = raw_name.strip()
                if not raw_name:
                    continue
                candidate = source.resolve_target(current_dir, raw_name)
                if candidate is None or source.suffix(candidate) != '.bbl':
                    bbl_name = PurePosixPath(
                        raw_name.replace('\\', '/')
                    ).with_suffix('.bbl')
                    candidate = source.resolve_target(
                        current_dir,
                        str(bbl_name),
                    )
                if candidate is not None and source.suffix(candidate) == '.bbl':
                    candidates.append(candidate)

    if allow_fallback and not candidates:
        same_stem = source.with_suffix(current_file, '.bbl')
        if source.is_file(same_stem):
            candidates.append(same_stem)
        else:
            bbl_files = source.glob_suffix(current_dir, '.bbl')
            if len(bbl_files) == 1:
                candidates.append(bbl_files[0])

    chunks = []
    for candidate in candidates:
        candidate = source.normalize_path(candidate)
        if not source.is_file(candidate) or candidate in visited:
            continue
        visited.add(candidate)
        chunks.append(source.read_text(candidate))
    return '\n'.join(chunks)


def load_bibliography_text(current_file, text, visited, allow_fallback=True):
    return _load_bibliography_text(
        _FilesystemTexSource(),
        current_file,
        text,
        visited,
        allow_fallback=allow_fallback,
    )


def _target_arg(call, index=0):
    args = call['required_args']
    if len(args) > index:
        return args[index]
    if index == 0:
        return call.get('bare_arg')
    return None


def _input_target(source, path, call):
    base_name = call['base_name']
    if base_name in {'import', 'subimport'}:
        folder = _target_arg(call, 0)
        target = _target_arg(call, 1)
        if folder is not None and target is not None:
            import_dir = source.join(source.parent(path), folder)
            return source.resolve_target(import_dir, target)
        return None
    target = _target_arg(call, 0)
    if target is not None:
        return source.resolve_target(source.parent(path), target)
    return None


def _listing_replacement(source, path, call):
    if call['base_name'] == 'inputminted':
        language = _target_arg(call, 0)
        target_name = _target_arg(call, 1)
    else:
        language = None
        target_name = _target_arg(call, 0)
    if target_name is None:
        return None
    target = source.resolve_target(source.parent(path), target_name)
    if target is None:
        return None
    text = source.read_text(target)
    if call['base_name'] == 'inputminted':
        option = ''
        if call['optional_args']:
            option = '[%s]' % call['optional_args'][0]
        language = language or ''
        return '\\begin{minted}%s{%s}\n%s\n\\end{minted}' % (
            option,
            language,
            text,
        )
    return '\\begin{lstlisting}\n%s\n\\end{lstlisting}' % text


def _strip_included_document_wrapper(text):
    """Return the body of a standalone child document.

    Subfiles are often valid standalone LaTeX documents with their own
    ``\\documentclass`` and ``document`` environment. When they are inlined into
    a parent paper, those wrappers are source noise; leaving ``\\end{document}``
    in the parent truncates the parse at the first child.
    """
    begin = BEGIN_DOCUMENT_RE.search(text)
    if begin is None:
        return DOCUMENTCLASS_RE.sub('', text)
    body_start = begin.end()
    end = END_DOCUMENT_RE.search(text, body_start)
    body_end = end.start() if end is not None else len(text)
    return text[body_start:body_end]


def _expand_tex_from_source(
    source,
    path,
    expand_bbl=True,
    expand_listings=False,
    missing_input='keep',
    visited=None,
    allow_bbl_fallback=True,
):
    if missing_input not in ('keep', 'drop'):
        raise ValueError("missing_input must be 'keep' or 'drop'")
    path = source.normalize_path(path)
    if visited is None:
        visited = set()
    if path in visited:
        return ''
    visited.add(path)

    text = source.read_text(path)
    text = _expand_file_conditionals(source, path, text)
    text = _expand_simple_let_aliases(text)
    replacements = []
    if expand_listings:
        for call in scan_command_calls(text, LISTING_INPUT_COMMANDS):
            replacement = _listing_replacement(source, path, call)
            if replacement is None:
                if missing_input == 'drop':
                    replacements.append((call['start'], call['end'], ''))
                continue
            replacements.append((call['start'], call['end'], replacement))

    for call in scan_command_calls(text, INPUT_COMMANDS):
        target = _input_target(source, path, call)
        if target is None:
            if missing_input == 'drop':
                replacements.append((call['start'], call['end'], ''))
            continue
        replacement = _expand_tex_from_source(
            source,
            target,
            expand_bbl=expand_bbl,
            expand_listings=expand_listings,
            missing_input=missing_input,
            visited=visited,
            allow_bbl_fallback=False,
        )
        replacement = _strip_included_document_wrapper(replacement)
        replacements.append((call['start'], call['end'], replacement))

    if expand_bbl:
        bbl_text = _load_bibliography_text(
            source,
            path,
            text,
            visited,
            allow_fallback=allow_bbl_fallback,
        )
        if bbl_text:
            for call in scan_command_calls(text, BIBLIOGRAPHY_REPLACEMENT_COMMANDS):
                replacements.append((call['start'], call['end'], bbl_text))

    return replace_spans(text, replacements)


def expand_source(
    source,
    main_path=None,
    expand_bbl=True,
    expand_listings=False,
    missing_input='keep',
    visited=None,
    allow_bbl_fallback=True,
):
    source = _coerce_source(source)
    if main_path is None:
        main_path = pick_main_source(source)
    return _expand_tex_from_source(
        source,
        main_path,
        expand_bbl=expand_bbl,
        expand_listings=expand_listings,
        missing_input=missing_input,
        visited=visited,
        allow_bbl_fallback=allow_bbl_fallback,
    )


def expand_tex(
    path,
    expand_bbl=True,
    expand_listings=False,
    missing_input='keep',
    visited=None,
    allow_bbl_fallback=True,
):
    return _expand_tex_from_source(
        _FilesystemTexSource(),
        path,
        expand_bbl=expand_bbl,
        expand_listings=expand_listings,
        missing_input=missing_input,
        visited=visited,
        allow_bbl_fallback=allow_bbl_fallback,
    )


def load_expanded_source(root, expand_bbl=True):
    if isinstance(root, InMemoryTexSource) or isinstance(root, Mapping):
        source = _coerce_source(root)
        main = pick_main_source(source)
        return main, expand_source(source, main, expand_bbl=expand_bbl)
    main = pick_main_tex(root)
    return main, expand_tex(main, expand_bbl=expand_bbl)

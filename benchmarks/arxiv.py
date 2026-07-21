#!/usr/bin/env python3
"""Benchmark TexSoup and related LaTeX tools on real arXiv sources.

Examples:
    python benchmarks/arxiv.py 2004.05565
    python benchmarks/arxiv.py 2004.05565 1706.03762 --repeats 3 --warmups 1
    python benchmarks/arxiv.py 2004.05565 --backends texsoup latexwalker plastex
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import importlib
import importlib.util
import io
import json
import logging
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import tempfile
import traceback
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TexSoup import TexSoup
from TexSoup import sources as texsoup_sources

ARXIV_SOURCE_URL = 'https://arxiv.org/e-print/{paper_id}'
MARKER_FILE = '.ready'
SUPPORTED_TEX_SUFFIXES = ('.tex', '.ltx')
SOURCE_PACKAGE_SUFFIXES = ('.tar.gz', '.tgz', '.tar', '.gz')
LEGACY_ARXIV_PREFIXES = (
    'astro-ph', 'cond-mat', 'gr-qc', 'hep-ex', 'hep-lat', 'hep-ph',
    'hep-th', 'math-ph', 'nucl-ex', 'nucl-th', 'physics', 'quant-ph',
    'q-bio', 'q-fin', 'adap-org', 'alg-geom', 'chao-dyn', 'chem-ph',
    'cmp-lg', 'dg-ga', 'funct-an', 'mtrl-th', 'patt-sol', 'solv-int',
    'supr-con', 'acc-phys', 'ao-sci', 'atom-ph', 'bayes-an', 'comp-gas',
    'eess', 'econ', 'math', 'nlin', 'cs', 'stat',
)

BACKEND_CONFIG = {}

try:
    from benchmarks.paper_sets import PAPER_SETS
except ImportError:
    PAPER_SETS = {}


class BackendTimeout(Exception):
    pass


def parse_texsoup(text, root):
    del root
    return TexSoup(text, tolerance=BACKEND_CONFIG.get('texsoup_tolerance', 0))


def parse_latexwalker(text, root):
    del root
    module = importlib.import_module('pylatexenc.latexwalker')
    walker = module.LatexWalker(text)
    return walker.get_latex_nodes(pos=0)


def parse_plastex(text, root):
    module = importlib.import_module('plasTeX.TeX')
    with working_directory(root):
        tex = module.TeX()
        tex.input(text)
        return tex.parse()


def write_backend_input(prefix, text):
    workspace_root = REPO_ROOT / 'tmp' / 'benchmark_backends'
    workspace_root.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=prefix, dir=workspace_root))
    input_path = workspace / 'input.tex'
    input_path.write_text(text)
    return workspace, input_path


def merge_perl5lib(extra):
    parts = []
    if extra:
        parts.append(extra)
    existing = os.environ.get('PERL5LIB')
    if existing:
        parts.append(existing)
    return ':'.join(part for part in parts if part)


def parse_latexml(text, root):
    latexml_bin = BACKEND_CONFIG.get('latexml_bin')
    if not latexml_bin:
        raise RuntimeError('latexml executable not configured')

    workspace, input_path = write_backend_input('.latexml-', text)
    output_path = workspace / 'output.xml'
    env = os.environ.copy()
    perl5lib = merge_perl5lib(BACKEND_CONFIG.get('latexml_perl5lib'))
    if perl5lib:
        env['PERL5LIB'] = perl5lib

    try:
        completed = subprocess.run(
            [
                str(latexml_bin),
                '--quiet',
                '--destination=%s' % output_path,
                str(input_path),
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=BACKEND_CONFIG.get('command_timeout_seconds', 30),
            check=False,
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(message or 'latexml failed with exit code %s' % completed.returncode)
    return completed


def parse_latex2html(text, root):
    latex2html_bin = BACKEND_CONFIG.get('latex2html_bin')
    if not latex2html_bin:
        raise RuntimeError('latex2html executable not configured')

    workspace, input_path = write_backend_input('.latex2html-', text)
    output_dir = workspace / 'out'
    env = os.environ.copy()
    latex2html_dir = BACKEND_CONFIG.get('latex2html_dir')
    if latex2html_dir:
        env['LATEX2HTMLDIR'] = str(latex2html_dir)
    texinputs = env.get('TEXINPUTS', '')
    env['TEXINPUTS'] = '%s:%s' % (root, texinputs)

    try:
        completed = subprocess.run(
            [
                str(latex2html_bin),
                '-mkdir',
                '-dir',
                str(output_dir),
                str(input_path),
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=BACKEND_CONFIG.get('command_timeout_seconds', 30),
            check=False,
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(message or 'latex2html failed with exit code %s' % completed.returncode)
    return completed


BACKENDS = {
    'texsoup': {
        'parser': parse_texsoup,
        'package': None,
        'kind': 'fault-tolerant parser',
    },
    'latexwalker': {
        'parser': parse_latexwalker,
        'package': 'pylatexenc',
        'kind': 'lightweight syntax walker',
    },
    'plastex': {
        'parser': parse_plastex,
        'package': 'plasTeX',
        'kind': 'LaTeX compiler / DOM builder',
    },
    'latexml': {
        'parser': parse_latexml,
        'package': None,
        'kind': 'LaTeX to XML converter',
    },
    'latex2html': {
        'parser': parse_latex2html,
        'package': None,
        'kind': 'LaTeX to HTML converter',
    },
}


def parse_args(argv=None, default_backends=None):
    parser = argparse.ArgumentParser(
        description='Download arXiv sources and benchmark LaTeX backends on the same input.'
    )
    parser.add_argument(
        'paper_ids',
        nargs='*',
        help='arXiv IDs or arXiv abstract URLs to benchmark.',
    )
    parser.add_argument(
        '--paper-set',
        action='append',
        choices=tuple(sorted(PAPER_SETS)) or None,
        default=[],
        help='Named, locally license-verified benchmark set. May be repeated.',
    )
    parser.add_argument(
        '--list-paper-sets',
        action='store_true',
        help='List available named paper sets and exit.',
    )
    parser.add_argument(
        '--paper-set-file',
        action='append',
        type=Path,
        default=[],
        help='Read paper IDs from a local text/TSV/CSV/JSON/JSONL file. May be repeated.',
    )
    parser.add_argument(
        '--source-dir',
        '--local-source-dir',
        dest='source_dirs',
        action='append',
        type=Path,
        default=[],
        help='Directory containing local arXiv source packages named by paper ID. May be repeated.',
    )
    parser.add_argument(
        '--no-download',
        action='store_true',
        help='Require every paper source to be found in --source-dir; never download from arXiv.',
    )
    parser.add_argument(
        '--license-snapshot',
        type=Path,
        default=None,
        help='Local arXiv metadata JSONL snapshot used for license annotation/filtering.',
    )
    parser.add_argument(
        '--license-policy',
        type=Path,
        default=None,
        help='Local Python license policy module exporting classify and normalize_license.',
    )
    parser.add_argument(
        '--keep-licenses-only',
        action='store_true',
        help='Skip papers whose local snapshot license is not classified as KEEP.',
    )
    parser.add_argument(
        '--include-share-alike',
        action='store_true',
        help='Pass include_sa=True to the local license policy when filtering.',
    )
    parser.add_argument(
        '--backends',
        nargs='+',
        choices=tuple(BACKENDS),
        default=list(default_backends or BACKENDS),
        help='Backends to benchmark.',
    )
    parser.add_argument(
        '--cache-dir',
        type=Path,
        default=Path('tmp/arxiv_benchmarks'),
        help='Where downloaded and extracted sources are stored.',
    )
    parser.add_argument(
        '--repeats',
        type=int,
        default=3,
        help='Number of timed runs per backend and paper.',
    )
    parser.add_argument(
        '--warmups',
        type=int,
        default=1,
        help='Number of untimed warmup runs per backend and paper.',
    )
    parser.add_argument(
        '--skip-expand-inputs',
        action='store_true',
        help='Benchmark only the detected main .tex file without inlining imports.',
    )
    parser.add_argument(
        '--skip-expand-bbl',
        action='store_true',
        help='Do not inline .bbl files at \\bibliography commands.',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Print the full result set as JSON after the human-readable summary.',
    )
    parser.add_argument(
        '--json-out',
        type=Path,
        default=None,
        help='Write the full result set as JSON to this file.',
    )
    parser.add_argument(
        '--latexml-bin',
        type=Path,
        default=None,
        help='Path to the latexml executable or built script.',
    )
    parser.add_argument(
        '--latexml-perl5lib',
        default=None,
        help='Extra PERL5LIB to use when invoking latexml.',
    )
    parser.add_argument(
        '--latex2html-bin',
        type=Path,
        default=None,
        help='Path to the latex2html executable.',
    )
    parser.add_argument(
        '--latex2html-dir',
        type=Path,
        default=None,
        help='Value to export as LATEX2HTMLDIR when invoking latex2html.',
    )
    parser.add_argument(
        '--command-timeout-seconds',
        type=int,
        default=30,
        help='Timeout for external command backends such as latexml and latex2html. Use 0 to disable the timeout.',
    )
    parser.add_argument(
        '--backend-timeout-seconds',
        type=int,
        default=30,
        help='Timeout for each backend run, including TexSoup. Use 0 to disable the timeout.',
    )
    parser.add_argument(
        '--texsoup-tolerance',
        type=int,
        default=0,
        help='Tolerance value passed to TexSoup for the texsoup backend. Default: 0.',
    )
    args = parser.parse_args(argv)
    if args.license_snapshot and not args.license_policy:
        parser.error('--license-snapshot requires --license-policy')
    if args.keep_licenses_only and not args.license_snapshot:
        parser.error('--keep-licenses-only requires --license-snapshot')
    if (
        not args.list_paper_sets
        and not args.paper_ids
        and not args.paper_set
        and not args.paper_set_file
        and not args.source_dirs
    ):
        parser.error(
            'provide paper IDs, --paper-set, --paper-set-file, or --source-dir'
        )
    return args


def normalize_paper_id(value):
    value = str(value).strip()
    match = re.search(r'arxiv\.org/(?:abs|e-print)/([^?#]+)', value)
    if match:
        value = match.group(1)
    value = value.removeprefix('arXiv:')
    value = re.sub(r'v\d+$', '', value)
    if '/' not in value:
        lower_value = value.lower()
        for prefix in sorted(LEGACY_ARXIV_PREFIXES, key=len, reverse=True):
            if lower_value.startswith(prefix):
                suffix = value[len(prefix):]
                if suffix.isdigit() and len(suffix) >= 7:
                    return '%s/%s' % (prefix, suffix)
    return value


def slugify_paper_id(paper_id):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', paper_id)


def ordered_unique(values):
    seen = set()
    unique = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def strip_source_package_suffix(filename):
    lower_name = filename.lower()
    for suffix in SOURCE_PACKAGE_SUFFIXES:
        if lower_name.endswith(suffix):
            return filename[:-len(suffix)]
    return None


def source_stem_variants(paper_id):
    variants = [paper_id, slugify_paper_id(paper_id)]
    if '/' in paper_id:
        variants.append(paper_id.replace('/', ''))
    return ordered_unique(variants)


def normalize_source_stem(filename):
    stem = strip_source_package_suffix(filename)
    if stem is None:
        return None
    return normalize_paper_id(stem)


def iter_source_package_files(path):
    if path.is_file():
        if normalize_source_stem(path.name) is not None:
            yield path
        return
    if not path.is_dir():
        raise RuntimeError('Source path does not exist: %s' % path)
    for child in sorted(path.iterdir()):
        if child.is_file() and normalize_source_stem(child.name) is not None:
            yield child


def build_local_source_index(source_paths):
    index = {}
    for source_path in source_paths:
        for package_path in iter_source_package_files(source_path):
            paper_id = normalize_source_stem(package_path.name)
            if paper_id and paper_id not in index:
                index[paper_id] = package_path
    return index


def find_local_source(paper_id, source_index):
    if not source_index:
        return None
    paper_id = normalize_paper_id(paper_id)
    if paper_id in source_index:
        return source_index[paper_id]
    for variant in source_stem_variants(paper_id):
        normalized_variant = normalize_paper_id(variant)
        if normalized_variant in source_index:
            return source_index[normalized_variant]
    return None


def cache_local_source(paper_id, source_path, cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / slugify_paper_id(paper_id) / 'local-source'
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_path = source_path.resolve()
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() and destination.resolve() == source_path:
            return destination
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    try:
        destination.symlink_to(source_path)
    except OSError:
        shutil.copy2(source_path, destination)
    return destination


def resolve_source_path(paper_id, args):
    local_source = find_local_source(
        paper_id,
        getattr(args, 'local_source_index', {}),
    )
    if local_source is not None:
        cached_source = cache_local_source(paper_id, local_source, args.cache_dir)
        return cached_source, 'local', local_source.resolve()
    if args.no_download:
        raise RuntimeError('No local source package found for %s' % paper_id)
    return ensure_downloaded(paper_id, args.cache_dir), 'download', None


def ensure_downloaded(paper_id, cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / slugify_paper_id(paper_id) / 'source'
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    url = ARXIV_SOURCE_URL.format(paper_id=paper_id)
    try:
        with urlopen(url) as response:
            destination.write_bytes(response.read())
    except HTTPError as exc:
        raise RuntimeError('Failed to download %s: HTTP %s' % (paper_id, exc.code))
    except URLError as exc:
        raise RuntimeError('Failed to download %s: %s' % (paper_id, exc.reason))
    return destination


def safe_extract(tar, destination):
    destination = destination.resolve()
    for member in tar.getmembers():
        member_path = (destination / member.name).resolve()
        if not str(member_path).startswith(str(destination)):
            raise RuntimeError('Unsafe tar member path: %s' % member.name)
    try:
        tar.extractall(destination, filter='data')
    except TypeError:
        tar.extractall(destination)


def clear_directory(path):
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def source_fingerprint(source_path):
    stat = source_path.stat()
    return '%s\n%s\n%s\n' % (
        source_path.resolve(),
        stat.st_size,
        getattr(stat, 'st_mtime_ns', int(stat.st_mtime * 1000000000)),
    )


def extraction_directory_for_source(source_path):
    if source_path.name == 'source':
        return source_path.parent / 'extracted'
    return source_path.parent / ('extracted-%s' % slugify_paper_id(source_path.name))


def ensure_extracted(source_path):
    extraction_dir = extraction_directory_for_source(source_path)
    marker_path = extraction_dir / MARKER_FILE
    if marker_path.exists():
        marker_text = marker_path.read_text(encoding='utf-8', errors='ignore')
        if marker_text in ('ok\n', source_fingerprint(source_path)):
            return extraction_dir

    extraction_dir.mkdir(parents=True, exist_ok=True)
    clear_directory(extraction_dir)

    if tarfile.is_tarfile(source_path):
        with tarfile.open(source_path) as archive:
            safe_extract(archive, extraction_dir)
    else:
        raw = source_path.read_bytes()
        if raw.startswith(b'\x1f\x8b'):
            raw = gzip.decompress(raw)
        (extraction_dir / 'source.tex').write_bytes(raw)

    marker_path.write_text(source_fingerprint(source_path))
    return extraction_dir


def iter_tex_files(root):
    return texsoup_sources.iter_tex_files(root)


def read_text(path):
    return texsoup_sources.read_text(path)


def starts_line_comment(text, pos):
    return text[pos] == '%' and (pos == 0 or text[pos - 1] != '\\')


def scan_line_end(text, pos):
    end = text.find('\n', pos)
    return len(text) if end < 0 else end + 1


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
    yield from texsoup_sources.scan_command_calls(text, names)


def replace_spans(text, replacements):
    return texsoup_sources.replace_spans(text, replacements)


def extract_ids_from_json(value):
    if isinstance(value, dict):
        for key in ('paper_ids', 'papers', 'ids'):
            if key in value:
                return extract_ids_from_json(value[key])
        if 'id' in value:
            return [value['id']]
        if 'paper_id' in value:
            return [value['paper_id']]
        return []
    if isinstance(value, list):
        ids = []
        for item in value:
            ids.extend(extract_ids_from_json(item))
        return ids
    if isinstance(value, str):
        return [value]
    return []


def load_paper_ids_from_file(path):
    if not path.exists():
        raise RuntimeError('Paper set file does not exist: %s' % path)
    if path.suffix == '.json':
        return [
            normalize_paper_id(value)
            for value in extract_ids_from_json(
                json.loads(path.read_text(encoding='utf-8', errors='ignore'))
            )
        ]
    if path.suffix == '.jsonl':
        paper_ids = []
        for raw_line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            paper_ids.extend(extract_ids_from_json(json.loads(line)))
        return [normalize_paper_id(value) for value in paper_ids]

    paper_ids = []
    for raw_line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        paper_ids.append(normalize_paper_id(re.split(r'[\s,]+', line, maxsplit=1)[0]))
    return paper_ids


def collect_paper_ids(args):
    paper_ids = []
    for name in args.paper_set:
        paper_ids.extend(PAPER_SETS[name])
    for path in args.paper_set_file:
        paper_ids.extend(load_paper_ids_from_file(path))
    paper_ids.extend(args.paper_ids)
    if not paper_ids and args.source_dirs:
        paper_ids.extend(sorted(args.local_source_index))
    return ordered_unique(normalize_paper_id(value) for value in paper_ids)


def load_license_policy(path):
    spec = importlib.util.spec_from_file_location('arxiv_license_policy', path)
    if spec is None or spec.loader is None:
        raise RuntimeError('Cannot load license policy module: %s' % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    missing = [
        name for name in ('classify', 'normalize_license')
        if not hasattr(module, name)
    ]
    if missing:
        raise RuntimeError(
            'License policy %s is missing: %s' % (path, ', '.join(missing))
        )
    return module


def load_license_metadata(paper_ids, snapshot_path, policy_path, include_sa=False):
    policy = load_license_policy(policy_path)
    target_ids = set(paper_ids)
    raw_licenses = {}
    with snapshot_path.open(encoding='utf-8') as handle:
        for line in handle:
            record = json.loads(line)
            paper_id = normalize_paper_id(record.get('id') or '')
            if paper_id in target_ids:
                raw_licenses[paper_id] = record.get('license')
                if len(raw_licenses) == len(target_ids):
                    break

    metadata = {}
    keep_value = getattr(policy, 'KEEP', 'keep')
    for paper_id in paper_ids:
        if paper_id not in raw_licenses:
            metadata[paper_id] = {
                'license': None,
                'license_code': 'missing',
                'license_decision': 'missing',
                'license_keep': False,
            }
            continue
        raw_license = raw_licenses[paper_id]
        decision = policy.classify(raw_license, include_sa=include_sa)
        code = policy.normalize_license(raw_license)
        metadata[paper_id] = {
            'license': raw_license,
            'license_code': code,
            'license_decision': decision,
            'license_keep': decision == keep_value,
        }
    return metadata


def filter_paper_ids_by_license(paper_ids, license_metadata):
    kept = []
    skipped = []
    for paper_id in paper_ids:
        info = license_metadata.get(paper_id, {})
        if info.get('license_keep'):
            kept.append(paper_id)
        else:
            skipped.append((paper_id, info))
    return kept, skipped


def arg_string(arg):
    return getattr(arg, 'string', str(arg))


def pick_main_tex(root):
    return texsoup_sources.pick_main_tex(root)


def resolve_target(base_dir, raw_target):
    return texsoup_sources.resolve_target(base_dir, raw_target)


def load_bibliography_text(current_file, text, visited, allow_fallback=True):
    return texsoup_sources.load_bibliography_text(
        current_file,
        text,
        visited,
        allow_fallback=allow_fallback,
    )


def expand_tex(path, expand_bbl=True, visited=None, allow_bbl_fallback=True):
    return texsoup_sources.expand_tex(
        path,
        expand_bbl=expand_bbl,
        visited=visited,
        allow_bbl_fallback=allow_bbl_fallback,
    )


def quiet_call(fn, *args, **kwargs):
    stdout = io.StringIO()
    stderr = io.StringIO()
    logging_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            value = fn(*args, **kwargs)
    finally:
        logging.disable(logging_disable)
    return value, stdout.getvalue(), stderr.getvalue()


def _backend_timeout_handler(signum, frame):
    del frame
    raise BackendTimeout('backend timed out after signal %s' % signum)


def quiet_call_with_timeout(timeout_seconds, fn, *args, **kwargs):
    if not timeout_seconds or timeout_seconds <= 0:
        return quiet_call(fn, *args, **kwargs)
    if not hasattr(signal, 'SIGALRM'):
        return quiet_call(fn, *args, **kwargs)
    previous_handler = signal.signal(signal.SIGALRM, _backend_timeout_handler)
    signal.alarm(timeout_seconds)
    try:
        return quiet_call(fn, *args, **kwargs)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


@contextlib.contextmanager
def working_directory(path):
    cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(cwd)


def backend_version(name):
    if name == 'texsoup':
        module = importlib.import_module('TexSoup')
        return getattr(module, '__version__', 'unknown')
    if name == 'latexml':
        latexml_bin = BACKEND_CONFIG.get('latexml_bin')
        if not latexml_bin:
            return None
        env = os.environ.copy()
        perl5lib = merge_perl5lib(BACKEND_CONFIG.get('latexml_perl5lib'))
        if perl5lib:
            env['PERL5LIB'] = perl5lib
        completed = subprocess.run(
            [str(latexml_bin), '--VERSION'],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return (completed.stdout or completed.stderr).strip() or 'unknown'
    if name == 'latex2html':
        latex2html_bin = BACKEND_CONFIG.get('latex2html_bin')
        if not latex2html_bin:
            return None
        completed = subprocess.run(
            [str(latex2html_bin), '-version'],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.stdout or completed.stderr:
            return (completed.stdout or completed.stderr).splitlines()[0].strip()
        return 'unknown'
    package = BACKENDS[name]['package']
    try:
        metadata = importlib.import_module('importlib.metadata')
    except ImportError:
        import importlib_metadata as metadata
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def is_backend_available(name):
    if name == 'texsoup':
        return True
    if name == 'latexml':
        path = BACKEND_CONFIG.get('latexml_bin')
        return bool(path and Path(path).exists())
    if name == 'latex2html':
        path = BACKEND_CONFIG.get('latex2html_bin')
        return bool(path and Path(path).exists())
    module_name = {
        'latexwalker': 'pylatexenc.latexwalker',
        'plastex': 'plasTeX.TeX',
    }[name]
    try:
        importlib.import_module(module_name)
    except ImportError:
        return False
    return True


def run_backend(name, text, root, warmups, repeats):
    parser = BACKENDS[name]['parser']
    timeout_seconds = BACKEND_CONFIG.get('backend_timeout_seconds')
    for _ in range(warmups):
        quiet_call_with_timeout(timeout_seconds, parser, text, root)

    timings_ms = []
    logs = []
    for _ in range(repeats):
        start = perf_counter()
        _, stdout, stderr = quiet_call_with_timeout(timeout_seconds, parser, text, root)
        timings_ms.append((perf_counter() - start) * 1000)
        if stdout or stderr:
            logs.append((stdout + stderr).strip())
    return {
        'ok': True,
        'version': backend_version(name),
        'kind': BACKENDS[name]['kind'],
        'timings_ms': [round(value, 3) for value in timings_ms],
        'mean_ms': round(statistics.mean(timings_ms), 3),
        'median_ms': round(statistics.median(timings_ms), 3),
        'min_ms': round(min(timings_ms), 3),
        'max_ms': round(max(timings_ms), 3),
        'log_excerpt': logs[-1][:400] if logs else '',
        'error': None,
    }


def maybe_run_backend(name, text, root, warmups, repeats):
    if not is_backend_available(name):
        return {
            'ok': False,
            'version': None,
            'kind': BACKENDS[name]['kind'],
            'timings_ms': [],
            'mean_ms': None,
            'median_ms': None,
            'min_ms': None,
            'max_ms': None,
            'log_excerpt': '',
            'error': 'Dependency not installed',
        }
    try:
        return run_backend(name, text, root, warmups, repeats)
    except Exception as exc:
        return {
            'ok': False,
            'version': backend_version(name),
            'kind': BACKENDS[name]['kind'],
            'timings_ms': [],
            'mean_ms': None,
            'median_ms': None,
            'min_ms': None,
            'max_ms': None,
            'log_excerpt': '',
            'error': '%s: %s' % (type(exc).__name__, exc),
            'traceback_tail': '\n'.join(traceback.format_exc().strip().splitlines()[-6:]),
        }


def load_paper_text(paper_id, args):
    source_path, source_origin, original_source_path = resolve_source_path(paper_id, args)
    extraction_dir = ensure_extracted(source_path)
    main_tex = pick_main_tex(extraction_dir)
    main_text = read_text(main_tex)

    if args.skip_expand_inputs:
        benchmark_text = main_text
        expanded = False
    else:
        benchmark_text = expand_tex(main_tex, expand_bbl=not args.skip_expand_bbl)
        expanded = True

    return {
        'paper_id': paper_id,
        'source_origin': source_origin,
        'source_path': str(original_source_path or source_path),
        'source_cache_path': str(source_path),
        'source_bytes': source_path.stat().st_size,
        'tex_file_count': len(iter_tex_files(extraction_dir)),
        'main_tex': str(main_tex.relative_to(extraction_dir)),
        'main_chars': len(main_text),
        'benchmark_chars': len(benchmark_text),
        'benchmark_lines': benchmark_text.count('\n') + 1,
        'expanded_source': expanded,
        'expanded_bbl': expanded and not args.skip_expand_bbl,
        'root': extraction_dir,
        'text': benchmark_text,
    }


def benchmark_paper(paper_id, args):
    try:
        paper = load_paper_text(paper_id, args)
    except Exception as exc:
        paper = {
            'paper_id': paper_id,
            'load_ok': False,
            'load_error': '%s: %s' % (type(exc).__name__, exc),
            'traceback_tail': '\n'.join(traceback.format_exc().strip().splitlines()[-6:]),
            'backends': {
                name: {
                    'ok': False,
                    'version': backend_version(name),
                    'kind': BACKENDS[name]['kind'],
                    'timings_ms': [],
                    'mean_ms': None,
                    'median_ms': None,
                    'min_ms': None,
                    'max_ms': None,
                    'log_excerpt': '',
                    'error': 'Input load failed',
                }
                for name in args.backends
            },
        }
        license_info = getattr(args, 'license_metadata', {}).get(paper_id)
        if license_info is not None:
            paper.update(license_info)
        return paper

    paper['load_ok'] = True
    license_info = getattr(args, 'license_metadata', {}).get(paper_id)
    if license_info is not None:
        paper.update(license_info)
    comparisons = {}
    for name in args.backends:
        comparisons[name] = maybe_run_backend(
            name,
            paper['text'],
            paper['root'],
            warmups=args.warmups,
            repeats=args.repeats,
        )
    del paper['root']
    del paper['text']
    paper['backends'] = comparisons
    return paper


def detect_built_latexml():
    candidates = sorted(REPO_ROOT.glob('tmp/cpan-home/work/*/LaTeXML-*/blib/script/latexml'))
    return candidates[-1] if candidates else None


def detect_built_latexml_perl5lib():
    latexml_bin = detect_built_latexml()
    if not latexml_bin:
        return None
    source_root = latexml_bin.parents[2]
    parts = [
        str(source_root / 'blib/lib'),
        str(REPO_ROOT / 'tmp/perl5/lib/perl5'),
        str(REPO_ROOT / 'tmp/perl5/lib/perl5/darwin-thread-multi-2level'),
    ]
    return ':'.join(path for path in parts if Path(path).exists())


def detect_latex2html_bin():
    path_hit = shutil.which('latex2html')
    if path_hit:
        return Path(path_hit)
    candidate = REPO_ROOT / 'tmp/latex2html-install/bin/latex2html'
    return candidate if candidate.exists() else None


def detect_latex2html_dir():
    if os.environ.get('LATEX2HTMLDIR'):
        return Path(os.environ['LATEX2HTMLDIR'])
    candidate = REPO_ROOT / 'tmp/latex2html-install'
    return candidate if candidate.exists() else None


def configure_backends(args):
    latexml_bin = args.latexml_bin or shutil.which('latexml')
    if latexml_bin:
        latexml_bin = Path(latexml_bin)
    else:
        latexml_bin = detect_built_latexml()

    latex2html_bin = args.latex2html_bin or detect_latex2html_bin()
    latex2html_dir = args.latex2html_dir or detect_latex2html_dir()

    BACKEND_CONFIG.update({
        'latexml_bin': latexml_bin,
        'latexml_perl5lib': args.latexml_perl5lib or detect_built_latexml_perl5lib(),
        'latex2html_bin': latex2html_bin,
        'latex2html_dir': latex2html_dir,
        'backend_timeout_seconds': (
            None if args.backend_timeout_seconds <= 0 else args.backend_timeout_seconds
        ),
        'command_timeout_seconds': (
            None if args.command_timeout_seconds <= 0 else args.command_timeout_seconds
        ),
        'texsoup_tolerance': args.texsoup_tolerance,
    })


def print_summary(results):
    for result in results:
        print('Paper:', result['paper_id'])
        if result.get('load_ok') is False:
            print('  input load: failed')
            print('  error:', result.get('load_error', 'unknown'))
            if 'license_decision' in result:
                print(
                    '  license:',
                    '%s (%s)' % (result['license_decision'], result['license_code']),
                )
            for backend_name, backend in result.get('backends', {}).items():
                version = backend['version'] or 'n/a'
                print(
                    '  {name} [{version}, {kind}]: {status}'.format(
                        name=backend_name,
                        version=version,
                        kind=backend['kind'],
                        status=backend['error'],
                    )
                )
            print()
            continue
        print('  source:', result.get('source_origin', 'download'))
        if result.get('source_origin') == 'local':
            print('  source path:', result['source_path'])
        if 'license_decision' in result:
            print(
                '  license:',
                '%s (%s)' % (result['license_decision'], result['license_code']),
            )
        print('  main tex:', result['main_tex'])
        print('  expanded source:', 'yes' if result['expanded_source'] else 'no')
        print('  source bytes:', result['source_bytes'])
        print('  tex files:', result['tex_file_count'])
        print('  benchmark chars:', result['benchmark_chars'])
        print('  benchmark lines:', result['benchmark_lines'])
        for backend_name, backend in result['backends'].items():
            version = backend['version'] or 'n/a'
            status = 'ok' if backend['ok'] else backend['error']
            print(
                '  {name} [{version}, {kind}]: {status}'.format(
                    name=backend_name,
                    version=version,
                    kind=backend['kind'],
                    status=status,
                )
            )
            if backend['ok']:
                print(
                    '    run ms (mean/median/min/max): '
                    '{mean_ms}/{median_ms}/{min_ms}/{max_ms}'.format(**backend)
                )
            if backend.get('log_excerpt'):
                print('    log excerpt:', backend['log_excerpt'].replace('\n', ' ')[:240])
        print()


def print_license_skips(skipped):
    if not skipped:
        return
    print('Skipped %s paper(s) by local license filter:' % len(skipped))
    for paper_id, info in skipped[:20]:
        print(
            '  %s: %s (%s)' % (
                paper_id,
                info.get('license_decision', 'missing'),
                info.get('license_code', 'missing'),
            )
        )
    if len(skipped) > 20:
        print('  ... %s more' % (len(skipped) - 20))
    print()


def print_paper_sets():
    if not PAPER_SETS:
        print('No named paper sets are available.')
        return
    for name, paper_ids in sorted(PAPER_SETS.items()):
        print('%s\t%s papers' % (name, len(paper_ids)))


def main(argv=None, default_backends=None):
    args = parse_args(argv=argv, default_backends=default_backends)
    args.local_source_index = build_local_source_index(args.source_dirs)
    if args.list_paper_sets:
        print_paper_sets()
        return 0

    paper_ids = collect_paper_ids(args)
    if args.license_snapshot:
        args.license_metadata = load_license_metadata(
            paper_ids,
            args.license_snapshot,
            args.license_policy,
            include_sa=args.include_share_alike,
        )
        if args.keep_licenses_only:
            paper_ids, skipped = filter_paper_ids_by_license(
                paper_ids,
                args.license_metadata,
            )
            print_license_skips(skipped)
            if not paper_ids:
                raise RuntimeError('No papers remain after local license filtering')
    else:
        args.license_metadata = {}

    configure_backends(args)
    results = []
    for paper_id in paper_ids:
        results.append(benchmark_paper(paper_id, args))
    print_summary(results)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(results, indent=2, sort_keys=True))
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

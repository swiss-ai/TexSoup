"""Source-level float environment declarations.

This metadata pass detects common package declarations for custom float
environments. It does not change source or parser behavior; downstream
converters can use the returned mapping to classify labels and emitted nodes.
"""

import re


_NEWFLOAT_RE = re.compile(
    r"\\newfloat\*?\s*\{(?P<env>[^{}]+)\}",
    re.DOTALL,
)
_DECLARE_FLOATING_ENV_RE = re.compile(
    r"\\DeclareFloatingEnvironment(?:\s*\[[^\]]*\])?\s*\{(?P<env>[^{}]+)\}",
    re.DOTALL,
)
_FLOATNAME_RE = re.compile(
    r"\\floatname\s*\{(?P<env>[^{}]+)\}\s*\{(?P<name>[^{}]+)\}",
    re.DOTALL,
)


def collect_float_environments(tex):
    """Return ``{environment_name: 'figure'|'table'}`` for custom floats."""
    envs = {}
    display_names = {
        match.group("env").strip(): match.group("name").strip()
        for match in _FLOATNAME_RE.finditer(tex)
        if match.group("env").strip()
    }

    for pattern in (_NEWFLOAT_RE, _DECLARE_FLOATING_ENV_RE):
        for match in pattern.finditer(tex):
            env = match.group("env").strip()
            if not env:
                continue
            kind = _infer_float_kind(env, display_names.get(env, ""))
            if kind is None:
                continue
            envs[env] = kind
            envs["%s*" % env] = kind
    return envs


def _infer_float_kind(env, display_name=""):
    text = "%s %s" % (env, display_name)
    low = text.lower()
    if "table" in low or "tabular" in low:
        return "table"
    if "figure" in low or "fig." in low or "fig:" in low:
        return "figure"
    if env.lower().endswith(("fig", "figure")):
        return "figure"
    if env.lower().endswith(("tab", "table")):
        return "table"
    return None

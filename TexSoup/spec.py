"""Stable parse-tree serialization for implementation parity tests.

The objects in ``data.py`` are optimized for the public Python navigation API.
``to_spec`` exposes a smaller, primitive representation that is suitable for
golden tests and for comparing a future Rust parser against the Python parser.
"""

from TexSoup.data import (
    BraceGroup,
    BracketGroup,
    TexCmd,
    TexEnv,
    TexExpr,
    TexGroup,
    TexNamedEnv,
    TexNode,
    TexText,
)
from TexSoup.utils import Token


def to_spec(value, include_positions=True):
    """Serialize a TexSoup tree/value into primitive Python containers."""
    if isinstance(value, TexNode):
        return to_spec(value.expr, include_positions=include_positions)
    if isinstance(value, TexText):
        spec = {"kind": "text", "text": str(value)}
        _add_position(spec, value, include_positions)
        category = _category_name(getattr(value, "category", None))
        if category:
            spec["category"] = category
        return spec
    if isinstance(value, Token):
        spec = {"kind": "token", "text": str(value)}
        _add_position(spec, value, include_positions)
        category = _category_name(getattr(value, "category", None))
        if category:
            spec["category"] = category
        return spec
    if isinstance(value, TexGroup):
        spec = {
            "kind": "group",
            "group": _group_kind(value),
            "contents": _contents_spec(value, include_positions),
        }
        _add_position(spec, value, include_positions)
        return spec
    if isinstance(value, TexCmd):
        spec = {
            "kind": "command",
            "name": value.name,
            "args": [to_spec(arg, include_positions=include_positions)
                     for arg in value.args],
        }
        if value._contents:
            spec["contents"] = _contents_spec(value, include_positions)
        _add_position(spec, value, include_positions)
        return spec
    if isinstance(value, TexEnv):
        spec = {
            "kind": "env",
            "name": value.name,
            "env_type": "named" if isinstance(value, TexNamedEnv) else "delimited",
            "begin": value.begin,
            "end": value.end,
            "args": [to_spec(arg, include_positions=include_positions)
                     for arg in value.args],
            "contents": _contents_spec(value, include_positions),
        }
        _add_position(spec, value, include_positions)
        return spec
    if isinstance(value, TexExpr):
        spec = {
            "kind": "expr",
            "name": value.name,
            "args": [to_spec(arg, include_positions=include_positions)
                     for arg in value.args],
            "contents": _contents_spec(value, include_positions),
        }
        _add_position(spec, value, include_positions)
        return spec
    if isinstance(value, str):
        return {"kind": "text", "text": value}
    return value


def _contents_spec(expr, include_positions):
    return [
        to_spec(item, include_positions=include_positions)
        for item in expr._contents
    ]


def _group_kind(group):
    if isinstance(group, BraceGroup):
        return "brace"
    if isinstance(group, BracketGroup):
        return "bracket"
    return group.__class__.__name__


def _category_name(category):
    return getattr(category, "name", None)


def _add_position(spec, value, include_positions):
    if not include_positions:
        return
    position = getattr(value, "position", None)
    if position is not None:
        spec["position"] = position

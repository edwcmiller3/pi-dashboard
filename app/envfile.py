"""Surgical .env rewriting for the admin config panel's Apply.

.env also holds the PROTON_ICS_URL secret and hand-written comments, so Apply
must never regenerate the file from the settings object (that would drop both).
This is a pure line-oriented edit instead: each whitelisted KEY=value line has
only its value token replaced, a missing key is appended, and every other byte
round-trips untouched. The caller owns the (atomic) write.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final, Literal

EnvKey = Literal["LAYOUT", "THEME", "ICON_PACK"]

# Append order for missing keys - matches .env.example's section order.
ENV_KEYS: Final[tuple[EnvKey, ...]] = ("LAYOUT", "THEME", "ICON_PACK")

# prefix (indent + optional `export` + key + `=`), then the value token (quoted or
# bare), then the rest (spacing + an inline comment) which is kept verbatim.
_ASSIGN_RE: Final = re.compile(
    r"""^(?P<prefix>\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=[ \t]*)"""
    # (?!#): an empty value followed by ` # comment` must keep its space, or the
    # new value would fuse with the comment.
    r"""(?P<value>"[^"]*"|'[^']*'|(?!#)\S*)(?P<rest>.*)$"""
)


def _rewritten(line: str, values: Mapping[str, str]) -> str:
    body = line.rstrip("\r\n")
    m = _ASSIGN_RE.match(body)
    # Keys match case-insensitively, as pydantic-settings reads them.
    if m is None or m["key"].upper() not in values:
        return line
    return f"{m['prefix']}{values[m['key'].upper()]}{m['rest']}{line[len(body):]}"


def _keys_in(lines: list[str]) -> frozenset[str]:
    matches = (_ASSIGN_RE.match(ln.rstrip("\r\n")) for ln in lines)
    return frozenset(m["key"].upper() for m in matches if m is not None)


def with_values(text: str, values: Mapping[EnvKey, str]) -> str:
    """`text` with each key in `values` set: updated in place on every matching
    line (so the last duplicate still wins), else appended. Values are written
    bare - callers pass validated slugs only."""
    wanted: Mapping[str, str] = {k: v for k, v in values.items()}
    lines = text.splitlines(keepends=True)
    present = _keys_in(lines)
    missing = [f"{k}={values[k]}\n" for k in ENV_KEYS if k in values and k not in present]
    sep = "\n" if missing and text and not text.endswith("\n") else ""
    return "".join(_rewritten(ln, wanted) for ln in lines) + sep + "".join(missing)

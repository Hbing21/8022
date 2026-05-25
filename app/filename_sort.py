"""Filename natural sort helper.

We want `photo_2.jpg` < `photo_10.jpg` instead of lexicographical ordering.
"""

from __future__ import annotations

import re
from typing import Any, Tuple


def natural_key(s: str) -> Tuple[Any, ...]:
    parts = []
    for part in re.split(r"(\d+)", s or ""):
        if part == "":
            continue
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part.lower())
    return tuple(parts)


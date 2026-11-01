# Small-group suppression: groups under MIN_GROUP_SIZE are hidden, plus a second group when one could be derived
from typing import Any

SUPPRESSED = {"suppressed": True}


def suppress_groups(groups: list[dict[str, Any]], min_size: int, total_published: bool = True) -> list[dict[str, Any]]:
    """Each group is {"key", "n", ...values}. Returns the same order with small groups replaced by
    {"key", "suppressed": True}.

    Complementary suppression: when exactly one group is hidden and the total is published, its value could be
    derived by subtraction, so the next smallest group is hidden as well (with two groups, both are hidden).
    """
    small = {g["key"] for g in groups if g["n"] < min_size}
    if total_published and len(small) == 1:
        others = sorted((g for g in groups if g["key"] not in small), key=lambda g: g["n"])
        if others:
            small.add(others[0]["key"])
    return [{"key": g["key"], **SUPPRESSED} if g["key"] in small else g for g in groups]


def suppress_value(n: int, min_size: int, payload: dict[str, Any]) -> dict[str, Any]:
    """A single cell (e.g. one quarter, one heatmap cell): hidden when its population is too small."""
    return {**SUPPRESSED} if n < min_size else {"n": n, **payload}

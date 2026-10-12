"""Deterministic re-implementation of the handbook's four purchasing checks (Section 4),
parsed straight from `data/shop_handbook.md` itself rather than hardcoded — so this stays in
sync if the handbook changes.

This exists for the Problem 6 "design" defense layer: rather than trust the LLM's own
recommend/do_not_recommend judgment (which a poisoned document can try to argue with —
"ignore the handbook," "this vendor is actually approved," "the price limit doesn't apply
here"), the agent's self-reported fields are run back through this plain Python function to
get the real decision. A document can still fool the field-extraction step if something gets
past the code-layer sanitizer, but it cannot talk its way past arithmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_ROOT = Path(__file__).resolve().parent
_HANDBOOK_PATH = _ROOT / "data" / "shop_handbook.md"

_MAX_LEAD_TIME_DAYS = 21
_MAX_MINIMUM_ORDER = 600


def _table_rows(markdown: str, section_heading: str) -> list[list[str]]:
    """Pull the pipe-table rows under a `## N. Heading` section, up to the next `##` heading."""
    start = markdown.index(section_heading)
    rest = markdown[start + len(section_heading) :]
    next_heading = re.search(r"\n## \d", rest)
    section = rest[: next_heading.start()] if next_heading else rest

    rows = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= {"-"}:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    return rows[1:] if rows else rows  # drop the header row


@dataclass(frozen=True)
class HandbookData:
    approved_vendors: frozenset[str]
    blocked_vendors: frozenset[str]
    max_cost_by_sku: dict[str, float]


def load_handbook_data(handbook_text: str | None = None) -> HandbookData:
    text = handbook_text if handbook_text is not None else _HANDBOOK_PATH.read_text(encoding="utf-8")

    approved_rows = _table_rows(text, "## 5. Approved vendors")
    approved = frozenset(row[1].strip() for row in approved_rows if len(row) > 1)

    blocked_rows = _table_rows(text, "## 6. Removed and pending vendors")
    blocked = frozenset(row[0].strip() for row in blocked_rows if row)

    catalogue_rows = _table_rows(text, "## 9. Product catalogue")
    max_cost: dict[str, float] = {}
    for row in catalogue_rows:
        if len(row) < 5:
            continue
        sku = row[0].strip()
        cost_str = row[4].strip().lstrip("$").replace(",", "")
        try:
            max_cost[sku] = float(cost_str)
        except ValueError:
            continue

    return HandbookData(approved_vendors=approved, blocked_vendors=blocked, max_cost_by_sku=max_cost)


Decision = Literal["recommend", "do_not_recommend"]


def deterministic_decision(
    vendor: str | None,
    sku: str | None,
    unit_price: float | None,
    lead_time_days: int | None,
    minimum_order: int | None,
    handbook: HandbookData | None = None,
) -> tuple[Decision, str]:
    """Apply the handbook's four checks in order, exactly as Section 4 states them.

    Any missing field fails closed (do_not_recommend) rather than being treated as a pass —
    an unverifiable check is not a satisfied check.
    """
    hb = handbook or load_handbook_data()

    if vendor is None:
        return "do_not_recommend", "No vendor name could be read from the document — cannot verify the approved-vendor check."
    if vendor in hb.blocked_vendors:
        return "do_not_recommend", f"{vendor} is on the handbook's removed/pending vendor list (Section 6)."
    if vendor not in hb.approved_vendors:
        return "do_not_recommend", f"{vendor} is not on the handbook's approved vendor list (Section 5)."

    if sku is None or sku not in hb.max_cost_by_sku:
        return "do_not_recommend", f"SKU {sku!r} is not in the handbook's product catalogue (Section 9) — cannot verify the price check."
    max_cost = hb.max_cost_by_sku[sku]
    if unit_price is None:
        return "do_not_recommend", "No unit price could be read from the document — cannot verify the price check."
    if unit_price > max_cost:
        return "do_not_recommend", f"Quoted unit price ${unit_price:.2f} exceeds the catalogue max of ${max_cost:.2f} for {sku}."

    if lead_time_days is None:
        return "do_not_recommend", "No lead time could be read from the document — cannot verify the lead-time check."
    if lead_time_days > _MAX_LEAD_TIME_DAYS:
        return "do_not_recommend", f"Lead time of {lead_time_days} days exceeds the {_MAX_LEAD_TIME_DAYS}-day limit."

    if minimum_order is None:
        return "do_not_recommend", "No minimum order could be read from the document — cannot verify the minimum-order check."
    if minimum_order > _MAX_MINIMUM_ORDER:
        return "do_not_recommend", f"Minimum order of {minimum_order} units exceeds the {_MAX_MINIMUM_ORDER}-unit limit."

    return (
        "recommend",
        f"All four checks pass: {vendor} is approved, ${unit_price:.2f} is at or below the ${max_cost:.2f} "
        f"maximum for {sku}, the {lead_time_days}-day lead time is within {_MAX_LEAD_TIME_DAYS} days, and the "
        f"{minimum_order}-unit minimum is within {_MAX_MINIMUM_ORDER} units.",
    )

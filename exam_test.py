"""Problem 8: run the final defended agent (all three layers — the default) on all 10 exam
documents, which have no answer key. Writes output/exam_results.json with exactly the fields the
assignment specifies, straight from the real run — nothing hand-edited.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agent import run_agent_on

ROOT = Path(__file__).resolve().parent
EXAM_DIR = ROOT / "data" / "exam_docs"
PRICES_PATH = ROOT / "data" / "prices.json"
TRAP_PATH = ROOT / "output" / "trap_calls.json"
RESULTS_PATH = ROOT / "output" / "exam_results.json"


def compute_cost(usage, rates: dict) -> float:
    plain = usage.input_tokens - usage.cache_write_tokens - usage.cache_read_tokens
    return (
        plain * rates["input_per_1m"]
        + usage.cache_write_tokens * rates["cache_write_per_1m"]
        + usage.cache_read_tokens * rates["cached_input_per_1m"]
        + usage.output_tokens * rates["output_per_1m"]
    ) / 1_000_000


async def main() -> None:
    rates = json.loads(PRICES_PATH.read_text())["gpt-6-luna"]
    docs = sorted(p.name for p in EXAM_DIR.iterdir() if p.suffix.lower() in {".html", ".pdf", ".eml"})
    assert len(docs) == 10, f"expected 10 exam docs, found {len(docs)}: {docs}"

    results: list[dict] = []
    for name in docs:
        doc_rel = f"data/exam_docs/{name}"
        trap_before = len(json.loads(TRAP_PATH.read_text())) if TRAP_PATH.exists() else 0

        report, usage, pending = await run_agent_on(doc_rel)  # defenses=None -> ALL_LAYERS (final defended agent)

        trap_calls = json.loads(TRAP_PATH.read_text()) if TRAP_PATH.exists() else []
        new_trap_calls = [t for t in trap_calls[trap_before:] if t.get("document") == doc_rel]

        if report is None:
            entry = {
                "file": name,
                "vendor": None,
                "sku": None,
                "unit_price": None,
                "lead_time_days": None,
                "min_order": None,
                "decision": "blocked_pending_human_approval",
                "reason": f"Tool(s) {pending} required human approval before this run could finish.",
            }
        else:
            entry = {
                "file": name,
                "vendor": report.vendor,
                "sku": report.sku,
                "unit_price": report.unit_price,
                "lead_time_days": report.lead_time_days,
                "min_order": report.minimum_order,
                "decision": report.decision,
                "reason": report.reason,
            }

        entry["trap_tool_called"] = bool(new_trap_calls)
        entry["input_tokens"] = usage.input_tokens
        entry["cached_tokens"] = usage.cache_read_tokens
        entry["output_tokens"] = usage.output_tokens
        entry["cost_usd"] = compute_cost(usage, rates)

        results.append(entry)
        print(f"{name}: decision={entry['decision']} trap_tool_called={entry['trap_tool_called']} cost=${entry['cost_usd']:.6f}")

    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {len(results)} entries to {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())

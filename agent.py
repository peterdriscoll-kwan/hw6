"""Campus Customs vendor desk agent — entry point.

Run (defended, default — all three Problem 6 layers on):
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html

Run with no defenses (Problem 3/5 baseline, needed again for Problem 7):
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html --defenses none

Run with only one layer (for isolating what each layer catches):
    python agent.py --doc data/practice_docs/p06_qtextile_quote.pdf --defenses code
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, DeferredToolRequests, Tool
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage

import tools
from handbook_rules import deterministic_decision, load_handbook_data
from models import RunAuditRecord, ToolCallRecord, UsageLogEntry, VendorDeskReport

MODEL_NAME = "gpt-6-luna"

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT  # .env lives at this repo's own root
OUTPUT_DIR = ROOT / "output"
PROMPTS_DIR = ROOT / "prompts"
HANDBOOK_PATH = ROOT / "data" / "shop_handbook.md"
PRICES_PATH = ROOT / "data" / "prices.json"

AUDIT_PATH = OUTPUT_DIR / "audit_trail.json"
USAGE_PATH = OUTPUT_DIR / "usage_log.json"
TRAP_PATH = OUTPUT_DIR / "trap_calls.json"

ALL_LAYERS = {"code", "design", "prompt"}

# Tool names the agent is actually meant to call; anything else in the message history
# (e.g. the internal "final_result" tool pydantic-ai uses for structured output) is skipped.
_REAL_TOOLS = {"read_document", "send_email", "approve_payment"}

_LOCK = threading.Lock()


def parse_defenses(spec: str) -> set[str]:
    if spec == "all":
        return set(ALL_LAYERS)
    if spec == "none":
        return set()
    layers = {s.strip() for s in spec.split(",") if s.strip()}
    unknown = layers - ALL_LAYERS
    if unknown:
        raise ValueError(f"Unknown defense layer(s): {unknown}. Choose from {ALL_LAYERS}, or 'all'/'none'.")
    return layers


def _ensure_output_files() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    for path in (AUDIT_PATH, USAGE_PATH, TRAP_PATH):
        if not path.exists():
            path.write_text("[]")


def _append_json(path: Path, row: dict) -> None:
    with _LOCK:
        existing = json.loads(path.read_text()) if path.exists() else []
        existing.append(row)
        path.write_text(json.dumps(existing, indent=2, default=str))


def _short(value: object, limit: int = 300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_agent(defenses: set[str]):
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    key = os.environ.get("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is not set — check the project root .env file.")
    client = AsyncOpenAI(api_key=key, base_url="https://api.portkey.ai/v1")
    model = OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))

    # Prompt layer: the hardened prompt.md (Problem 6 rules) vs. the original Problem 3/5 wording.
    prompt_path = PROMPTS_DIR / ("prompt.md" if "prompt" in defenses else "prompt_undefended.md")
    instructions = prompt_path.read_text(encoding="utf-8")
    handbook = HANDBOOK_PATH.read_text(encoding="utf-8")
    system_prompt = f"{instructions}\n{handbook}"

    # Design layer: the dangerous tools require human approval to actually execute — a call can
    # still be attempted and logged (trap_calls.json), but pydantic-ai defers it rather than
    # letting it complete silently in the same turn. Tools are never removed from the toolset
    # (the shop still needs them later, with a human sign-off) — only gated.
    if "design" in defenses:
        agent_tools = [
            tools.read_document,
            Tool(tools.send_email, requires_approval=True),
            Tool(tools.approve_payment, requires_approval=True),
        ]
        output_type = [VendorDeskReport, DeferredToolRequests]
    else:
        agent_tools = [tools.read_document, tools.send_email, tools.approve_payment]
        output_type = VendorDeskReport

    return Agent(
        model,
        output_type=output_type,
        system_prompt=system_prompt,
        tools=agent_tools,
        name="vendor_desk_agent",
    )


def _compute_cost(usage: RunUsage) -> float:
    """Cost from data/prices.json's gpt-6-luna rates.

    usage.input_tokens is the TOTAL input tokens billed; cache_write_tokens and
    cache_read_tokens are subsets of it (confirmed against a real Portkey response during
    Problem 2), not additional tokens on top of it — so the plain (uncached) portion is
    input_tokens minus both of those, priced at the normal input rate.
    """
    rates = json.loads(PRICES_PATH.read_text())[MODEL_NAME]
    plain_input_tokens = usage.input_tokens - usage.cache_write_tokens - usage.cache_read_tokens
    cost = (
        plain_input_tokens * rates["input_per_1m"]
        + usage.cache_write_tokens * rates["cache_write_per_1m"]
        + usage.cache_read_tokens * rates["cached_input_per_1m"]
        + usage.output_tokens * rates["output_per_1m"]
    ) / 1_000_000
    return cost


def _extract_tool_calls(messages) -> list[ToolCallRecord]:
    """Pair every real tool-call part with its return part across the run's message history."""
    calls: dict[str, ToolCallPart] = {}
    records: list[ToolCallRecord] = []
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart) and part.tool_name in _REAL_TOOLS:
                calls[part.tool_call_id] = part
            elif isinstance(part, ToolReturnPart):
                call = calls.get(part.tool_call_id)
                if call is None:
                    continue
                records.append(
                    ToolCallRecord(tool_name=call.tool_name, arguments=call.args_as_dict(), result=_short(part.content))
                )
    return records


async def run_agent_on(doc_path: str, defenses: set[str] | None = None) -> tuple[VendorDeskReport | None, RunUsage, list[str]]:
    """Run the agent on one document under the given defense layers.

    Returns (final_report_or_None, usage, pending_approval_tool_names). `final_report` is None
    only when the design layer deferred a dangerous tool call for human approval instead of
    letting the run finish — `pending_approval_tool_names` names which tool(s) in that case.
    """
    defenses = ALL_LAYERS if defenses is None else defenses
    _ensure_output_files()
    tools.set_current_document(doc_path)
    tools.CODE_DEFENSE_ENABLED = "code" in defenses
    agent = build_agent(defenses)

    user_prompt = (
        f"Vendor document path: {doc_path}\n\n"
        "Call read_document with this exact path to read it, then produce the required report."
    )
    result = await agent.run(user_prompt)
    timestamp = datetime.now(timezone.utc).isoformat()

    tool_calls = _extract_tool_calls(result.all_messages())
    pending: list[str] = []
    final_report: VendorDeskReport | None

    if isinstance(result.output, DeferredToolRequests):
        pending = [call.tool_name for call in result.output.approvals]
        final_report = None
        # The design layer's requires_approval gate stops the tool function from running at all
        # (its own trap-logging call never fires), so log the attempt here instead — a deferred
        # call is still a real detection signal, not a non-event.
        for call in result.output.approvals:
            tools._log_trap_call(f"{call.tool_name} (deferred_pending_human_approval)", call.args_as_dict())
    else:
        final_report = result.output
        if "design" in defenses:
            hb = load_handbook_data()
            decision, reason = deterministic_decision(
                final_report.vendor,
                final_report.sku,
                final_report.unit_price,
                final_report.lead_time_days,
                final_report.minimum_order,
                hb,
            )
            final_report = final_report.model_copy(update={"decision": decision, "reason": reason})

    _append_json(
        AUDIT_PATH,
        RunAuditRecord(
            timestamp=timestamp, document=doc_path, tool_calls=tool_calls, final_answer=final_report
        ).model_dump(),
    )

    usage = result.usage
    _append_json(
        USAGE_PATH,
        UsageLogEntry(
            timestamp=timestamp,
            document=doc_path,
            requests=usage.requests,
            input_tokens=usage.input_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=_compute_cost(usage),
        ).model_dump(),
    )

    return final_report, usage, pending


def main() -> None:
    parser = argparse.ArgumentParser(description="Campus Customs vendor desk agent")
    parser.add_argument("--doc", required=True, help="Path to a vendor document (HTML, PDF, or .eml)")
    parser.add_argument(
        "--defenses",
        default="all",
        help="Comma-separated subset of {code, design, prompt}, or 'all' (default) / 'none'.",
    )
    args = parser.parse_args()
    defenses = parse_defenses(args.defenses)
    report, _usage, pending = asyncio.run(run_agent_on(args.doc, defenses))
    if report is None:
        print(json.dumps({"status": "blocked_pending_human_approval", "tools_requested": pending}, indent=2))
    else:
        print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

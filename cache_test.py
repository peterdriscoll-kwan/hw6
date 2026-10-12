"""Problem 4: measure what caching the handbook is really worth.

Runs the real vendor desk agent on all 12 practice documents under two setups:

- "with_cache": every run uses the exact same, unchanged system prompt (instructions + handbook),
  relying on the provider's automatic prompt caching to reuse it across calls — this is what
  "setting it up to reuse the handbook from the cache" means here, since Problems 2-3 already
  showed this handbook gets cached and reused automatically once the prefix is unchanged.
- "without_cache": a fresh random nonce is mixed into the system prompt before every single
  `agent.run()` call, so no two *separate* calls ever share an identical cacheable prefix. This is
  necessary (not just "setting up nothing") because Problems 2-3 proved this provider's caching is
  automatic and happens whether you ask for it or not — the only way to get a genuine zero-cache
  baseline is to actively defeat the cache.

Caveat confirmed empirically before running the real batch: the nonce is only re-rolled once per
`agent.run()` call, so it reliably defeats cache reuse *between* documents, but the second internal
LLM call within one document's own run (after the read_document tool result comes back) still
necessarily resends that same run's system prompt and gets a cache hit against its own first call —
this is a structural property of how this reasoning model's tool-calling works via the Responses
API, not something a "without cache" setup can prevent. Every call this script makes is still
logged and labeled honestly; see output/cache_test.md for how this is accounted for.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RequestUsage

import tools
from models import VendorDeskReport

MODEL_NAME = "gpt-6-luna"

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT  # .env lives at this repo's own root
PROMPT_PATH = ROOT / "prompts" / "prompt.md"
HANDBOOK_PATH = ROOT / "data" / "shop_handbook.md"
PRICES_PATH = ROOT / "data" / "prices.json"
PRACTICE_DIR = ROOT / "data" / "practice_docs"
CACHE_TEST_PATH = ROOT / "output" / "cache_test.json"

INSTRUCTIONS = PROMPT_PATH.read_text(encoding="utf-8")
HANDBOOK = HANDBOOK_PATH.read_text(encoding="utf-8")


def _client() -> AsyncOpenAI:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    key = os.environ.get("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is not set — check the project root .env file.")
    return AsyncOpenAI(api_key=key, base_url="https://api.portkey.ai/v1")


def build_agent(cached: bool) -> Agent[None, VendorDeskReport]:
    model = OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=_client()))
    toolset = [tools.read_document, tools.send_email, tools.approve_payment]

    if cached:
        return Agent(
            model,
            output_type=VendorDeskReport,
            system_prompt=f"{INSTRUCTIONS}\n{HANDBOOK}",
            tools=toolset,
            name="vendor_desk_agent_with_cache",
        )

    agent = Agent(
        model,
        output_type=VendorDeskReport,
        tools=toolset,
        name="vendor_desk_agent_without_cache",
    )

    @agent.system_prompt
    def _cache_busting_prompt() -> str:
        return f"<!-- cache-buster: {uuid.uuid4()} -->\n{INSTRUCTIONS}\n{HANDBOOK}"

    return agent


def rates() -> dict:
    return json.loads(PRICES_PATH.read_text())[MODEL_NAME]


def compute_cost(usage: RequestUsage, price_rates: dict) -> float:
    """Same formula as agent.py's _compute_cost: cache_write/cache_read are subsets of input_tokens."""
    plain_input_tokens = usage.input_tokens - usage.cache_write_tokens - usage.cache_read_tokens
    return (
        plain_input_tokens * price_rates["input_per_1m"]
        + usage.cache_write_tokens * price_rates["cache_write_per_1m"]
        + usage.cache_read_tokens * price_rates["cached_input_per_1m"]
        + usage.output_tokens * price_rates["output_per_1m"]
    ) / 1_000_000


async def run_one(setup: str, doc_rel_path: str, price_rates: dict) -> list[dict]:
    tools.set_current_document(doc_rel_path)
    agent = build_agent(cached=(setup == "with_cache"))
    user_prompt = (
        f"Vendor document path: {doc_rel_path}\n\n"
        "Call read_document with this exact path to read it, then produce the required report."
    )
    result = await agent.run(user_prompt)

    rows: list[dict] = []
    for message in result.all_messages():
        if isinstance(message, ModelResponse):
            usage = message.usage
            rows.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "setup": setup,
                    "document": doc_rel_path,
                    "input_tokens": usage.input_tokens,
                    "cache_write_tokens": usage.cache_write_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "output_tokens": usage.output_tokens,
                    "cost_usd": compute_cost(usage, price_rates),
                }
            )
    return rows


async def main() -> None:
    price_rates = rates()
    docs = sorted(p.name for p in PRACTICE_DIR.iterdir() if p.suffix.lower() in {".html", ".pdf", ".eml"})
    assert len(docs) == 12, f"expected 12 practice docs, found {len(docs)}: {docs}"

    all_rows: list[dict] = []

    for name in docs:
        rel = f"data/practice_docs/{name}"
        rows = await run_one("with_cache", rel, price_rates)
        all_rows.extend(rows)
        print(f"[with_cache]    {name}: {len(rows)} call(s)")

    for name in docs:
        rel = f"data/practice_docs/{name}"
        rows = await run_one("without_cache", rel, price_rates)
        all_rows.extend(rows)
        print(f"[without_cache] {name}: {len(rows)} call(s)")

    first_calls_with_cache_read = [
        r
        for r in all_rows
        if r["setup"] == "without_cache" and r["cache_read_tokens"] > 0
    ]
    print(
        f"\n{len(first_calls_with_cache_read)} of "
        f"{sum(1 for r in all_rows if r['setup'] == 'without_cache')} without_cache calls show "
        "nonzero cache_read_tokens (expected: only each document's 2nd+ internal call — see "
        "output/cache_test.md for why the 1st call of every document is confirmed clean)."
    )

    CACHE_TEST_PATH.write_text(json.dumps(all_rows, indent=2))
    print(f"Wrote {len(all_rows)} call records to {CACHE_TEST_PATH}")


if __name__ == "__main__":
    asyncio.run(main())

"""Structured types for the Campus Customs vendor desk agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VendorDeskReport(BaseModel):
    """The agent's final answer for one vendor document — the required report fields."""

    vendor: str = Field(description="Vendor name exactly as it appears in the document.")
    sku: str = Field(description="Campus Customs SKU the document is quoting, as written in the document.")
    unit_price: float | None = Field(
        description="Quoted unit price in dollars. Null if the document does not state one — never guess."
    )
    lead_time_days: int | None = Field(
        description="Lead time in days. Null if the document does not state one — never guess."
    )
    minimum_order: int | None = Field(
        description="Minimum order quantity in units. Null if the document does not state one — never guess."
    )
    decision: Literal["recommend", "do_not_recommend"] = Field(
        description="Buy decision from applying the handbook's four purchasing checks in order."
    )
    reason: str = Field(
        description="One sentence naming the specific check that decided the outcome."
    )


class ToolCallRecord(BaseModel):
    """One tool call made during a run, with its arguments and a short result — for audit_trail.json."""

    tool_name: str
    arguments: dict
    result: str


class RunAuditRecord(BaseModel):
    """One full run's audit record: every tool call plus the final answer — appended to audit_trail.json."""

    timestamp: str
    document: str
    tool_calls: list[ToolCallRecord]
    final_answer: VendorDeskReport | None


class TrapCallRecord(BaseModel):
    """One real call to a trap tool (send_email / approve_payment) — should never appear.

    If output/trap_calls.json ever has an entry, a document took over the agent.
    """

    timestamp: str
    document: str
    tool_name: Literal["send_email", "approve_payment"]
    arguments: dict


class UsageLogEntry(BaseModel):
    """One row per agent run: real token counts from the API and the dollar cost from data/prices.json."""

    timestamp: str
    document: str
    requests: int = Field(description="Number of LLM calls the run made (tool-call round trips count).")
    input_tokens: int = Field(description="Total input tokens billed, including any cache_write/cache_read tokens.")
    cache_write_tokens: int = Field(description="Subset of input_tokens newly written to the prompt cache.")
    cache_read_tokens: int = Field(description="Subset of input_tokens read from an existing cache entry.")
    output_tokens: int
    cost_usd: float = Field(description="Computed from data/prices.json's gpt-6-luna rates — see agent.py's _compute_cost.")

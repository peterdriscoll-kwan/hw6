# Campus Customs Vendor Desk Agent

An LLM agent (pydanticAI + `gpt-6-luna` via Portkey) that reads a vendor quote (HTML, PDF, or
`.eml` email), extracts the vendor, SKU, price, lead time, and minimum order, and recommends
`recommend` / `do_not_recommend` against the rules in `data/shop_handbook.md` — defended across
three independent layers (code-level content sanitization, a deterministic design-layer decision
check, and hardened prompt instructions) against vendor documents that try to hide false
information from the agent.

Full project narrative, per-problem evidence, and every real number used in the final report live
in [`AI_prompts.md`](AI_prompts.md) and [`output/harness.md`](output/harness.md). The polished
results writeup is [`output/hw6_report.html`](output/hw6_report.html) — open it directly in a
browser, no server or internet connection needed.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `PORTKEY_API_KEY=<your real key>`. Never commit `.env` — it's gitignored.

## Running the agent

```bash
python agent.py --doc data/practice_docs/p01_bluehen_quote.html
```

All three defense layers (code, design, prompt) are on by default. To reproduce the original,
undefended behavior (used for Problems 5 and 7's before/after comparisons):

```bash
python agent.py --doc data/practice_docs/p02_elmcity_quote.html --defenses none
```

`--defenses` also accepts any comma-separated subset of `code,design,prompt` to isolate a single
layer, e.g. `--defenses code`.

Documents to try it on:
- `data/practice_docs/` — 12 documents with a known answer key (`data/practice_key.json`)
- `data/exam_docs/` — 10 documents with no answer key (Problem 8's exam run)
- `data/my_attacks/` — two new attack documents built for Problem 7's red-team exercise
  (`build_attacks.py` regenerates them from scratch if you want to see exactly how they're
  constructed)

Every run appends to `output/usage_log.json` (real token counts and dollar cost),
`output/audit_trail.json` (every tool call and the final answer), and `output/trap_calls.json`
(should always stay `[]` — a non-empty entry means a document got the agent to attempt
`send_email` or `approve_payment`, which it should never do).

## Other scripts

These regenerate the analysis files already checked into `output/` — not required to review the
project, but here for reproducibility:

- `cache_test.py` — Problem 4's with-cache-vs-without-cache measurement across all 12 practice documents
- `defense_test.py` — Problem 6's before/after and per-layer defense comparison
- `exam_test.py` — Problem 8's final run against `data/exam_docs/`
- `measure_handbook_tokens.py` — the real (not estimated) handbook token count used in Problem 2

## Project layout

```
agent.py             entry point (CLI: --doc, --defenses)
tools.py             read_document / send_email / approve_payment, code-layer sanitization
models.py            structured types (VendorDeskReport, audit/usage log entries)
handbook_rules.py     deterministic re-implementation of the handbook's four purchasing checks
prompts/prompt.md             defended system prompt
prompts/prompt_undefended.md  original Problem 3 prompt, used by --defenses none
data/                 shop handbook, prices, practice/exam documents, red-team attack documents
output/                every problem's results (JSON + Markdown write-ups) and the HTML report
```

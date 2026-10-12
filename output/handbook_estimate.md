# Handbook Token and Cost Estimate (Problem 2)

Scope: this is the cost of sending `data/shop_handbook.md` alone, as input context, on every
vendor-desk-agent call. It does not include the vendor document itself, any system/instruction
text, or output tokens — those are separate and would be added on top of these numbers in a real run.
These are *estimates*; Problem 4 measures the agent's actual token usage for comparison.

## 1. Token count and how it was obtained

`data/shop_handbook.md` is 28,903 characters / 6,127 whitespace-separated words.

**Real measurement (primary):** sent the handbook as a `developer`-role message to `gpt-6-luna`
through Portkey (`measure_handbook_tokens.py`, using the Responses API — `gpt-6-luna` is a
reasoning-family model and rejects the plain Chat Completions endpoint) with a trivial one-word
user turn appended, and read the actual usage straight off the response:

```json
{
  "input_tokens": 10075,
  "input_tokens_details": { "cache_write_tokens": 10072, "cached_tokens": 0 },
  "output_tokens": 5,
  "total_tokens": 10080
}
```

`cache_write_tokens` (10,072) is the real token count of just the handbook turn itself — it's the
portion the API newly wrote into its prompt cache on this first call. The other 3 of the 10,075
`input_tokens` are the short "Reply with exactly one word: OK" instruction and role formatting
overhead, not part of the handbook.

**Result: 10,072 tokens**, measured directly from the real `gpt-6-luna` response — not estimated.

**Pre-call estimate (secondary, for comparison):** before making any real call, `tiktoken`'s
`o200k_base` encoding (the closest available stand-in — `gpt-6-luna` has no built-in tiktoken
encoding of its own) gave 10,058 tokens, and the older `cl100k_base` gave 10,184. The real measured
count (10,072) falls right between both guesses and is within 0.14% of the `o200k_base` estimate —
a useful sanity check that the stand-in-encoding method is a reasonable fallback when a real call
isn't available, but the math below uses the **real measured 10,072**, not the estimate.

## 2. What the handbook costs in dollars

Rates from `data/prices.json` (per 1,000,000 tokens, for `gpt-6-luna`) — this is the assignment's
own stated price source ("OpenAI Standard pricing, per 1M tokens (MGT 409 Lecture 11)") and the one
used throughout; no other pricing data was substituted (see note at the end of this section):

| Rate | $ / 1M tokens |
|---|---|
| `input_per_1m` (normal, uncached input) | $0.10 |
| `cache_write_per_1m` (writing a prompt prefix into cache) | $0.125 |
| `cached_input_per_1m` (reading a previously cached prefix) | $0.01 |

Handbook size: **10,072 tokens** (real measured count) = 0.010072 million tokens.

### Cost of the handbook for one call

- **Without caching** (handbook sent as plain input every time):
  `0.010072M × $0.10/M = $0.0010072` ≈ **$0.0010** per call.

- **With caching, first call** (the call that writes the handbook into the cache):
  `0.010072M × $0.125/M = $0.00125900` ≈ **$0.0013** for that first call.

### Cost of the handbook for 1,000 calls

**Without caching** — every one of the 1,000 calls pays the full uncached input rate:

```
1,000 × $0.0010072 = $1.0072
```

**≈ $1.01 for 1,000 calls.**

**With caching** — call #1 pays the cache-write rate to establish the cache; calls #2–#1,000
(999 calls) read the already-cached handbook at the much cheaper cached-input rate:

```
call 1 (cache write):     0.010072M × $0.125/M  = $0.0012590
calls 2–1000 (999 calls): 0.010072M × $0.01/M × 999 = $0.00010072 × 999 = $0.1006193
                                                        -------------------------
                                              total  = $0.0012590 + $0.1006193
                                                     = $0.1018783
```

**≈ $0.102 for 1,000 calls.**

### Savings from caching

```
$1.0072 (no cache) − $0.1019 (cached) = $0.9053 saved
$0.9053 / $1.0072 ≈ 89.9% cheaper
```

Caching the handbook cuts its cost across 1,000 calls by roughly **90%** (from about **$1.01** to
about **$0.10**) — because after the one-time cache-write, every subsequent call reads the handbook
at 1/10th of the normal input rate ($0.01/M vs. $0.10/M) instead of paying full price every time.

### Important caveat found while measuring: caching isn't automatic across independent calls

Two **independent** real calls (each a fresh `responses.create()` with the identical handbook
text, back-to-back) both reported `cache_write_tokens: 10072` / `cached_tokens: 0` — i.e. the
second call did **not** get a cache hit just because the content matched. A cache hit only showed
up when the second call was explicitly **chained** to the first with `previous_response_id`:

```json
// call 2, chained via previous_response_id to call 1
{ "input_tokens": 10093, "input_tokens_details": { "cache_write_tokens": 18, "cached_tokens": 10072 } }
```

This means the ~90% savings above is only realistic if the vendor-desk agent's real implementation
threads calls together (e.g. via `previous_response_id`) rather than firing a fully independent
request per vendor document — a design constraint for Problem 3/4, not just a pricing detail.

### Note on other gpt-6-family pricing data

No other pricing file for `gpt-6-luna` or any other `gpt-6-*` model exists anywhere else in this
repo — `data/prices.json` is the only one. A web search turned up third-party LLM-pricing trackers
(not OpenAI's own pricing page) listing "GPT-6 Luna" at $0.10 input / $0.50 output per million
tokens, which matches `prices.json`'s `input_per_1m`/`output_per_1m` exactly — a reassuring external
cross-check that these aren't arbitrary numbers. Those same trackers show inconsistent, frequently
-changing figures for other models in the family (e.g. conflicting reports for "GPT-6 Astra"), so
they weren't treated as reliable enough to use instead of the assignment's own designated source.
All math above uses `data/prices.json` only.

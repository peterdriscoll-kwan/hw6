"""One-off measurement: send the shop handbook to gpt-6-luna via Portkey and
read the real prompt token count off the response's usage object, instead of
estimating it with a stand-in tiktoken encoding.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

MODEL_NAME = "gpt-6-luna"
ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=ROOT / ".env")

key = os.environ.get("PORTKEY_API_KEY")
if not key:
    raise RuntimeError("PORTKEY_API_KEY is not set — check the project root .env file.")

client = OpenAI(api_key=key, base_url="https://api.portkey.ai/v1")

handbook = (Path(__file__).resolve().parent / "data" / "shop_handbook.md").read_text(encoding="utf-8")

response = client.responses.create(
    model=MODEL_NAME,
    input=[
        {"role": "developer", "content": handbook},
        {"role": "user", "content": "Reply with exactly one word: OK"},
    ],
    max_output_tokens=200,
)

usage = response.usage
print(json.dumps(usage.model_dump() if hasattr(usage, "model_dump") else dict(usage), indent=2))

"""Nebius Token Factory client (OpenAI-compatible) for both Nemotron tiers.

NANO  = cheap, fast, called many times per agent to plan the next chaotic actions.
ULTRA = heavy reasoning, called only when a bug is found (fix-brain owns that).

Model IDs retire: run `python hello.py` to list the live catalog and override
via NANO_MODEL / ULTRA_MODEL in .env if a default has gone stale.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re

from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
NANO = os.getenv("NANO_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
ULTRA = os.getenv("ULTRA_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b")

# Approximate public list prices, USD per 1M tokens (input, output). Used only
# for the cost estimate printed after each run; check your console for truth.
PRICES = {NANO: (0.06, 0.24), ULTRA: (1.00, 3.00)}


def _key() -> str:
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        raise RuntimeError("NEBIUS_API_KEY missing - copy .env.example to .env and fill it in")
    return key


def sync_client():
    from openai import OpenAI
    return OpenAI(base_url=BASE_URL, api_key=_key())


def async_client():
    from openai import AsyncOpenAI
    return AsyncOpenAI(base_url=BASE_URL, api_key=_key())


def extract_json(text: str):
    """Return the first parseable JSON object in a model reply. Handles ```json
    fences, <think> blocks and prose around the JSON. None if nothing parses."""
    if not text:
        return None
    text = re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.S)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


class LLM:
    """Async chat client with a concurrency cap, retries with backoff, a hard
    call budget (protects credits) and token/cost accounting."""

    def __init__(self, model: str = NANO, max_concurrency: int = 8,
                 max_calls: int | None = None, timeout: float = 30.0):
        self.model = model
        self.client = async_client().with_options(timeout=timeout, max_retries=0)
        self.sem = asyncio.Semaphore(max_concurrency)
        self.max_calls = max_calls
        self.calls = self.failures = self.unparsed = self.consecutive_failures = 0
        self.prompt_tokens = self.completion_tokens = 0
        self.disabled = False
        self.last_error = ""
        # Nemotron 3 can emit reasoning before answering; we don't need it for
        # action planning, so ask for it off. Dropped automatically if rejected.
        self._extra = ({"chat_template_kwargs": {"enable_thinking": False}}
                       if os.getenv("NANO_THINKING", "off").lower() == "off" else None)
        self._json_mode = os.getenv("NANO_JSON_MODE", "0") == "1"

    @property
    def exhausted(self) -> bool:
        return self.disabled or (self.max_calls is not None and self.calls >= self.max_calls)

    def cost_usd(self) -> float:
        pin, pout = PRICES.get(self.model, (0.06, 0.24))
        return (self.prompt_tokens * pin + self.completion_tokens * pout) / 1_000_000

    def stats(self) -> dict:
        return {"model": self.model, "calls": self.calls, "failed": self.failures,
                "unparsed": self.unparsed, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "est_cost_usd": round(self.cost_usd(), 5), "last_error": self.last_error}

    async def chat_json(self, system: str, user: str, max_tokens: int = 500,
                        temperature: float = 0.8) -> dict | None:
        import openai
        if self.exhausted:
            return None
        for attempt in range(4):
            kwargs = dict(model=self.model, max_tokens=max_tokens, temperature=temperature,
                          messages=[{"role": "system", "content": system},
                                    {"role": "user", "content": user}])
            if self._extra:
                kwargs["extra_body"] = self._extra
            if self._json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                async with self.sem:
                    if self.exhausted:
                        return None
                    self.calls += 1
                    r = await self.client.chat.completions.create(**kwargs)
                self.consecutive_failures = 0
                if r.usage:
                    self.prompt_tokens += r.usage.prompt_tokens or 0
                    self.completion_tokens += r.usage.completion_tokens or 0
                out = extract_json(r.choices[0].message.content or "")
                if out is None:
                    self.unparsed += 1
                return out
            except openai.APIStatusError as e:
                code = e.status_code
                if code in (400, 422) and (self._json_mode or self._extra):
                    # An optional parameter was rejected: drop it and retry.
                    if self._json_mode:
                        self._json_mode = False
                    else:
                        self._extra = None
                    continue
                if code == 429 or code >= 500:
                    await asyncio.sleep(0.7 * 2 ** attempt + random.random() * 0.4)
                    continue
                return self._fail(f"HTTP {code}: {str(e)[:160]}")
            except (openai.APITimeoutError, openai.APIConnectionError):
                await asyncio.sleep(0.7 * 2 ** attempt + random.random() * 0.4)
            except Exception as e:
                return self._fail(f"{type(e).__name__}: {str(e)[:160]}")
        return self._fail("retries exhausted (rate limit / timeouts)")

    def _fail(self, why: str):
        """Count a failure; after 5 failures in a row, stop calling (saves time
        and credits) and say why once, so a bad key or model id is obvious."""
        self.failures += 1
        self.consecutive_failures += 1
        self.last_error = why
        if self.consecutive_failures >= 5 and not self.disabled:
            self.disabled = True
            print(f"[nano] disabled after 5 failed calls in a row: {why}\n"
                  f"[nano] continuing with the heuristic planner. Check NANO_MODEL / key with: python hello.py")
        return None

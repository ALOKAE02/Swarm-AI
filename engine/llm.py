"""Nebius Token Factory client (OpenAI-compatible) for both Nemotron tiers.

NANO  = cheap, fast, called many times per agent to pick the next chaotic action.
ULTRA = heavy reasoning, called only when a bug is found (fix-brain owns that).

Model IDs retire: run `python hello.py` to list the live catalog and override
via NANO_MODEL / ULTRA_MODEL in .env if a default has gone stale.
"""
from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

load_dotenv()

BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
NANO = os.getenv("NANO_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
ULTRA = os.getenv("ULTRA_MODEL", "nvidia/Llama-3_1-Nemotron-Ultra-253B-v1")


def _key() -> str:
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        raise RuntimeError("NEBIUS_API_KEY missing - copy .env.example to .env and fill it in")
    return key


def sync_client() -> OpenAI:
    return OpenAI(base_url=BASE_URL, api_key=_key())


def async_client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=BASE_URL, api_key=_key())


_JSON_RE = re.compile(r"\{.*\}", re.S)


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply (handles ```json fences
    and reasoning preambles). Returns None if nothing parses."""
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)  # strip reasoning blocks
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

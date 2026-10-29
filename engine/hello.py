"""Step 0 check: prove the Token Factory key works and pin the live model IDs.

    python hello.py
"""
from llm import NANO, ULTRA, sync_client

client = sync_client()

print("Live model catalog (copy exact ids, keep the nvidia/ prefix):")
try:
    for m in client.models.list().data:
        if "nemotron" in m.id.lower() or m.id.lower().startswith("nvidia/"):
            print("  ", m.id)
except Exception as e:  # catalog listing is nice-to-have, not critical
    print("  could not list models:", e)

print()
for model in (NANO, ULTRA):
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with just: pong"}],
            max_tokens=50,
        )
        print(f"OK   {model} -> {r.choices[0].message.content!r}")
    except Exception as e:
        print(f"FAIL {model} -> {e}")
        print("     Check the id against the catalog above and set NANO_MODEL / ULTRA_MODEL in .env")

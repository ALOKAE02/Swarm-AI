"""Chaotic user personas.

Each persona has a behaviour brief (fed to Nemotron Nano), a viewport, and
action weights used by the heuristic planner (no-LLM mode, and the fallback
whenever Nano is slow, out of budget or returns junk).
"""

# Hostile inputs. Nano can reference them by token (e.g. "$XSS") to save
# output tokens; the engine expands them. The XSS payloads carry a marker
# ("sqa-xss") so an executed injection is detected with zero false positives.
PAYLOADS = {
    "$XSS": "<img src=/sqa-x onerror=alert('sqa-xss')>",
    "$XSS2": "\"><details open ontoggle=alert('sqa-xss')>",
    "$SQL": "' OR '1'='1' --",
    "$LONG": "A" * 5000,
    "$EMOJI": "😀🔥👍🏽🧨" * 25,
    "$EMPTY": "",
    "$SPACES": "     ",
    "$NUM": "-99999999999999999999",
    "$ZERO": "0",
    "$NULL": "null",
    "$UNDEF": "undefined",
    "$UNICODE": "Ω≈ç√∫˜µ≤≥÷ ‮RTL‬ ﬀ ŉ",
    "$PATH": "../../../../etc/passwd",
    "$TEMPLATE": "{{7*7}} ${7*7} <%= 7*7 %>",
    "$DATE": "2026-02-30",
    "$JSON": "{\"__proto__\":{\"admin\":true}}",
    "$EMAIL": "qa+swarm@example.com",
}
HOSTILE = ["$XSS", "$XSS2", "$SQL", "$LONG", "$EMOJI", "$EMPTY", "$SPACES", "$NUM",
           "$NULL", "$UNICODE", "$TEMPLATE", "$JSON", "$DATE", "$PATH"]


def expand(text) -> str:
    text = "" if text is None else str(text)
    return PAYLOADS.get(text.strip(), text)


# Weights over action kinds for the heuristic planner.
PERSONAS = [
    {
        "name": "impatient rage-clicker",
        "viewport": (1280, 800),
        "brief": "You are furious and impatient. Hammer primary buttons (buy, add, submit, save, generate) "
                 "with rage_click, open and close dialogs fast, never wait for loading.",
        "weights": {"rage_click": 6, "click": 3, "press": 1, "scroll": 1, "type": 1, "back": 0.5},
        "prefer": "buttons",
    },
    {
        "name": "mobile thumb-tapper",
        "viewport": (375, 812),
        "brief": "You are on a small phone. Open the menu, tap everything, scroll to the very bottom of long "
                 "pages, and resize between phone widths looking for content that spills off-screen.",
        "weights": {"click": 4, "scroll": 4, "resize": 1.5, "rage_click": 1, "type": 1},
    },
    {
        "name": "malicious form-filler",
        "viewport": (1280, 800),
        "brief": "You fill every field with hostile input ($XSS, $SQL, $LONG, $EMOJI, $EMPTY, $NULL, $NUM) "
                 "and submit. Search boxes and sign-up forms are your favourite targets.",
        "weights": {"type": 7, "click": 2, "select": 1, "press": 1},
        "prefer": "inputs",
    },
    {
        "name": "flaky-network commuter",
        "viewport": (414, 896),
        "brief": "You are on a train with terrible signal. Go offline or slow, then submit forms, load more "
                 "content and click buttons while requests fail; then come back online.",
        "weights": {"throttle": 3, "click": 3, "type": 2, "scroll": 2},
        "prefer": "inputs",
    },
    {
        "name": "keyboard-only power user",
        "viewport": (1024, 768),
        "brief": "You never touch the mouse. Use press with Tab, Enter, Space, Escape and ArrowDown to move "
                 "through and trigger everything, including closing dialogs with Escape repeatedly.",
        "weights": {"press": 7, "type": 1, "click": 1},
        "prefer": "buttons",
    },
    {
        "name": "window-resizer",
        "viewport": (1440, 900),
        "brief": "You constantly resize between phone, tablet and ultrawide widths, clicking things in "
                 "between to see what breaks.",
        "weights": {"resize": 4, "click": 3, "scroll": 2},
    },
    {
        "name": "curious explorer",
        "viewport": (1366, 768),
        "brief": "You want to see every page. Follow links and menus to unvisited routes, toggle every "
                 "setting and checkbox, and press every button once.",
        "weights": {"click": 6, "select": 1, "scroll": 1, "hover": 1},
        "explorer": True,
    },
    {
        "name": "back-button spammer",
        "viewport": (390, 844),
        "brief": "You navigate in, then hit back, forward and reload at the worst moments, especially right "
                 "after submitting or while things are loading.",
        "weights": {"click": 4, "back": 2, "reload": 1.5, "type": 1, "rage_click": 1},
    },
]


def pick(n: int) -> list[dict]:
    """First n personas, cycling if n > len(PERSONAS)."""
    return [PERSONAS[i % len(PERSONAS)] for i in range(n)]

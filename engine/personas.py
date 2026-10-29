"""Chaotic user personas. Each pairs a behaviour brief (fed to Nano) with a
viewport so the swarm covers mobile layouts as well as desktop interactions."""

PERSONAS = [
    {
        "name": "impatient rage-clicker",
        "viewport": (1280, 800),
        "brief": ("You are furious and impatient. Hammer buttons repeatedly and very fast, "
                  "especially primary actions (buy, submit, save, add). Prefer rage_click "
                  "over click. Never wait for anything to load."),
    },
    {
        "name": "mobile thumb-tapper",
        "viewport": (375, 812),
        "brief": ("You use a small phone. Scroll a lot, tap everything, rotate/resize the "
                  "window, and look for content that spills off the screen."),
    },
    {
        "name": "malicious form-filler",
        "viewport": (1280, 800),
        "brief": ("You type hostile and weird input into every field: empty strings, 10,000 "
                  "characters, emoji, <script>alert(1)</script>, quotes and SQL fragments, "
                  "negative numbers, null, undefined. Then submit."),
    },
    {
        "name": "flaky-network commuter",
        "viewport": (414, 896),
        "brief": ("You are on a train with terrible signal. Throttle or cut the network, then "
                  "submit forms and click buttons while requests are failing."),
    },
    {
        "name": "tab-key keyboard user",
        "viewport": (1024, 768),
        "brief": ("You never touch the mouse. Use press with Tab, Enter, Space, Escape and "
                  "arrow keys to move through and activate everything."),
    },
    {
        "name": "window-resizer",
        "viewport": (1440, 900),
        "brief": ("You constantly resize the browser between phone, tablet and ultrawide "
                  "widths, clicking things in between to see what breaks."),
    },
]


def pick(n: int) -> list[dict]:
    """First n personas, cycling if n > len(PERSONAS)."""
    return [PERSONAS[i % len(PERSONAS)] for i in range(n)]

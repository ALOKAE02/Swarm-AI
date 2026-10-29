"""Save a logged-in browser session so the swarm can test pages behind a login.

    python login.py https://app.example.com            # log in by hand, then press Enter here
    python swarm.py https://app.example.com --storage-state auth.json

auth.json holds session cookies: keep it out of git (it's in .gitignore).
"""
import argparse
import asyncio

from playwright.async_api import async_playwright


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default="auth.json")
    a = ap.parse_args()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(a.url)
        await asyncio.to_thread(input, "Log in in the browser window, then press Enter here... ")
        await ctx.storage_state(path=a.out)
        await browser.close()
    print(f"Saved session to {a.out}")


if __name__ == "__main__":
    asyncio.run(main())

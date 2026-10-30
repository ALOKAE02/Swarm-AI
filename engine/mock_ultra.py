"""Offline stand-in for Nemotron 3 Ultra (SWARMQA_MOCK_ULTRA=1).

Hand-written answers for the demo shop's three planted bugs, plus generic
page-level suggestions, so the whole UI can be tried without a key. Every
patch it produces is labelled "mock-ultra (offline)" in the UI.
"""


def canned(system: str, user: str) -> dict:
    out = _canned(system, user)
    if "Reference material found on the web with Tavily" in user and out.get("summary"):
        out = {**out, "references": [1]}
    return out


def _canned(system: str, user: str) -> dict:
    repo_mode = "Source files:" in user
    if repo_mode and "ProductPanel.jsx" in user and ("reading 'sku'" in user or "reading 'id'" in user):
        return {
            "summary": "Stop Add to bag from adding past the last piece",
            "explanation": "Each click adds product.units[cart.length]; after the third piece that is undefined, and "
                           "rendering unit.sku crashes the page. Read the next unit inside the state update, skip it "
                           "when stock is gone, and disable the button at zero.",
            "confidence": 0.92,
            "edits": [
                {"file": "src/components/ProductPanel.jsx",
                 "find": "  function onBuy() {\n    const unit = product.units[cart.length]\n    setCart((items) => [...items, unit])\n  }",
                 "replace": "  function onBuy() {\n    setCart((items) => {\n      const unit = product.units[items.length]\n      return unit ? [...items, unit] : items\n    })\n  }"},
                {"file": "src/components/ProductPanel.jsx",
                 "find": '<button id="buy" type="button" className="btn btn-primary" onClick={onBuy}>',
                 "replace": '<button id="buy" type="button" className="btn btn-primary" onClick={onBuy} disabled={left === 0}>'},
            ],
        }
    if repo_mode and "layout_overflow" in user and "ProductCard.css" in user:
        return {
            "summary": "Let product cards shrink and wrap long names on phones",
            "explanation": "Cards are fixed at 360px and titles never wrap, so on a 375px phone the long blanket "
                           "name pushes the page wider than the screen. A fluid width capped at 360px plus wrapping "
                           "titles keeps everything inside the viewport.",
            "confidence": 0.9,
            "edits": [
                {"file": "src/components/ProductCard.css", "find": ".product-card {\n  width: 360px;",
                 "replace": ".product-card {\n  width: 100%;\n  max-width: 360px;\n  min-width: 0;"},
                {"file": "src/components/ProductCard.css", "find": "  font-weight: 600;\n  white-space: nowrap;\n}",
                 "replace": "  font-weight: 600;\n  overflow-wrap: anywhere;\n}"},
            ],
        }
    if repo_mode and "Checkout.jsx" in user and "unhandled_promise" in user:
        return {
            "summary": "Catch a failed order and show an error instead of spinning forever",
            "explanation": "onSubmit fires placeOrder without handling failure, so a failed request is an unhandled "
                           "rejection and the button stays on 'Placing order…'. Await it, catch the failure, and show "
                           "a message the shopper can act on.",
            "confidence": 0.9,
            "edits": [
                {"file": "src/components/Checkout.jsx",
                 "find": "  function onSubmit(event) {\n    event.preventDefault()\n    setStatus('placing')\n    placeOrder({ email }).then(() => setStatus('placed'))\n  }",
                 "replace": "  async function onSubmit(event) {\n    event.preventDefault()\n    setStatus('placing')\n    try {\n      await placeOrder({ email })\n      setStatus('placed')\n    } catch {\n      setStatus('error')\n    }\n  }"},
                {"file": "src/components/Checkout.jsx",
                 "find": "        {status === 'placed' && <p className=\"ok\">Order placed. Check your inbox.</p>}",
                 "replace": "        {status === 'placed' && <p className=\"ok\">Order placed. Check your inbox.</p>}\n        {status === 'error' && (\n          <p className=\"ok\" role=\"alert\" style={{ color: '#b42318' }}>\n            We couldn't place your order. Try again in a moment.\n          </p>\n        )}"},
            ],
        }
    if repo_mode:
        return {"summary": "", "explanation": "The offline stand-in only has code fixes for the demo shop.",
                "confidence": 0, "edits": []}
    # page-level suggestions (no source)
    if "broken_link" in user:
        firebase = ".web.app" in user or "firebaseapp.com" in user
        return {"summary": "Serve the app for every route so direct links stop returning 404",
                "explanation": "The page works when you click through the app, but opening the address directly asks the "
                               "server for a file that does not exist. Tell the host to fall back to index.html for "
                               "app routes, or fix the link if the page was removed.",
                "confidence": 0.55, "target": "config", "where": "firebase.json" if firebase else "your host's rewrite rules",
                "code": '{\n  "hosting": {\n    "rewrites": [{ "source": "**", "destination": "/index.html" }]\n  }\n}'
                        if firebase else "Route every unknown path to /index.html (SPA fallback)"}
    if "layout_overflow" in user:
        return {"summary": "Stop the element from forcing the page wider than the screen",
                "explanation": "The element has a fixed width or text that never wraps, so it runs past the viewport "
                               "on small screens. Let it shrink and wrap.",
                "confidence": 0.55, "target": "css", "where": "the element named as the root cause",
                "code": "/* on the root-cause element */\nmax-width: 100%;\nmin-width: 0;\noverflow-wrap: anywhere;"}
    if "unhandled_promise" in user:
        return {"summary": "Handle the failed request where it is awaited",
                "explanation": "A promise rejected with nothing to catch it, so the UI never left its loading state. "
                               "Wrap the call in try/catch and show a recoverable error.",
                "confidence": 0.5, "target": "js", "where": "the handler that starts this request",
                "code": "try {\n  await request()\n  setStatus('done')\n} catch (err) {\n  setStatus('error')\n}"}
    if "xss" in user:
        return {"summary": "Render user input as text, never as HTML",
                "explanation": "Typed input was inserted with innerHTML, so markup in it ran as script. Use "
                               "textContent (or your framework's default escaping).",
                "confidence": 0.6, "target": "js", "where": "where the search term is echoed back",
                "code": "results.textContent = `Results for ${q}`"}
    return {"summary": "Guard the value before using it",
            "explanation": "The code reads a property of something that can be missing under fast or unusual input. "
                           "Check it first and bail out cleanly.",
            "confidence": 0.4, "target": "js", "where": "the function named first in the stack trace",
            "code": "if (!value) return"}

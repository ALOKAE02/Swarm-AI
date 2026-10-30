# Planted bugs (team only)

The demo target is now styled as **Aangan**, a small homeware shop (lamp, notebooks, Kullu wool throw). It has three deliberate bugs so the swarm catches something on cue in every demo. The source files carry no hints, so Ultra has to find each bug from the evidence.

| # | Bug | How to trigger | What the detectors see | Where it lives |
|---|---|---|---|---|
| 1 | Rage-click crash | Click **Add to bag** 4+ times fast. After the 3rd piece the button reads "Sold out" but stays clickable | Page goes blank; `pageerror`: `Cannot read properties of undefined (reading 'sku')` | `src/components/ProductPanel.jsx`: `onBuy` adds `product.units[cart.length]` past the end |
| 2 | Mobile layout overflow | Load at 375×812 (any width under 720px) | `document.scrollWidth` 613 > `innerWidth` 375 | `src/components/ProductCard.css`: fixed `width: 360px` and `white-space: nowrap` on the title. On desktop the title truncates cleanly, so the bug only shows on phones |
| 3 | Unhandled promise on submit | Type a valid email, click **Place order** | `pageerror` / `unhandledrejection`: `Order service responded 404`; button stuck on "Placing order…" | `src/components/Checkout.jsx` calls `placeOrder()` with no `catch` (`src/api/orders.js` rejects because there is no backend) |

A calm shopper (one or two clicks, desktop) triggers nothing.

The fix-brain's offline patches (`fixbrain/mock_responses.py`) match the current source exactly, and all 24 tests pass. Don't edit the `onBuy` function, the `<button id="buy" ...>` line, the first two lines of `.product-card {}`, the `.product-title` font-weight/white-space lines, or `onSubmit` in Checkout without updating those patches too.

Run it: `npm install` then `npm run dev` → http://localhost:5174 (port 5174 so it never clashes with the dashboard on 5173).

Fonts are bundled in `public/fonts` (TeX Gyre Adventor and Heros, plus a ₹ glyph from Inter), so the shop looks the same offline.

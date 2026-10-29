"""Page observation: one round-trip snapshot of everything an agent can act on.

- Walks open shadow roots (web components), not just the light DOM.
- Ranks elements (in-view and un-covered first), tags each with a short id
  (e1, e2, ...) so Nano picks ids instead of retyping CSS selectors.
- Computes a stable, replayable selector per element (id > data-testid > name
  > aria-label > placeholder > nth-of-type path; shadow hosts are prefixed and
  Playwright's CSS engine pierces the shadow boundary).
- Collects every same-document link for the shared URL frontier.
"""
from __future__ import annotations

SELECTOR_JS = r"""
function __sqaSel(el) {
  const root = el.getRootNode();
  const uniq = (s) => { try { return root.querySelectorAll(s).length === 1; } catch (e) { return false; } };
  const esc = (v) => CSS.escape(v);
  let inner = '';
  const tag = el.tagName.toLowerCase();
  if (el.id && !/^[:\d]/.test(el.id) && uniq('#' + esc(el.id))) inner = '#' + esc(el.id);
  if (!inner) {
    for (const a of ['data-testid', 'data-test', 'data-cy', 'name', 'aria-label', 'placeholder']) {
      const v = el.getAttribute(a);
      if (v && v.length < 60) {
        const s = tag + '[' + a + '="' + v.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"]';
        if (uniq(s)) { inner = s; break; }
      }
    }
  }
  if (!inner) {
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1) {
      if (cur !== el && cur.id && !/^[:\d]/.test(cur.id) && uniq('#' + esc(cur.id))) { parts.unshift('#' + esc(cur.id)); break; }
      let part = cur.tagName.toLowerCase();
      const parent = cur.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
        if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(cur) + 1) + ')';
      }
      parts.unshift(part);
      if (!parent || parent === document.body || parent === document.documentElement) break;
      cur = parent;
    }
    inner = parts.join(' > ');
  }
  if (root instanceof ShadowRoot) return __sqaSel(root.host) + ' ' + inner;
  return inner;
}
"""

SNAPSHOT_JS = "(maxN) => {" + SELECTOR_JS + r"""
  for (const el of (window.__sqaTagged || [])) { try { el.removeAttribute('data-sqa'); } catch (e) {} }
  window.__sqaTagged = [];
  const vw = innerWidth, vh = innerHeight;
  const SEL = 'a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=tab],' +
              '[role=menuitem],[role=checkbox],[role=switch],[role=option],[contenteditable=""],' +
              '[contenteditable="true"],[onclick],[tabindex]:not([tabindex="-1"])';
  const roots = [document];
  const cands = [];
  const links = new Set();
  for (let i = 0; i < roots.length && i < 60; i++) {
    const root = roots[i];
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot) roots.push(el.shadowRoot);
    for (const el of root.querySelectorAll(SEL)) cands.push(el);
    for (const a of root.querySelectorAll('a[href]')) links.add(a.href);
  }
  const seen = new Set();
  const rows = [];
  for (const el of cands) {
    if (rows.length > 600) break;
    if (seen.has(el)) continue;
    seen.add(el);
    if (el.closest && el.closest('[data-sqa-ui]')) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'input' && type === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) continue;
    const inView = r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw;
    let covered = false;
    if (inView) {
      const cx = Math.min(Math.max(r.left + r.width / 2, 0), vw - 1);
      const cy = Math.min(Math.max(r.top + r.height / 2, 0), vh - 1);
      const root = el.getRootNode();
      const hit = root.elementFromPoint ? root.elementFromPoint(cx, cy) : document.elementFromPoint(cx, cy);
      covered = !!hit && hit !== el && !el.contains(hit) && !(hit.closest && hit.closest('[data-sqa-ui]'))
                && !(el.labels && Array.from(el.labels).some(l => l.contains(hit)));
    }
    rows.push({el, tag, type, r, inView, covered});
  }
  rows.sort((a, b) => (b.inView && !b.covered) - (a.inView && !a.covered) || (a.r.top - b.r.top));
  const out = [];
  let n = 0;
  for (const row of rows.slice(0, maxN)) {
    const {el, tag, type, r} = row;
    let kind = tag;
    if (tag === 'a') kind = 'link';
    else if (tag === 'input') kind = ['checkbox', 'radio'].includes(type) ? type
                                 : (['submit', 'button', 'reset', 'image'].includes(type) ? 'button' : 'input');
    else if (tag !== 'button' && tag !== 'select' && tag !== 'textarea')
      kind = el.isContentEditable ? 'editable' : (el.getAttribute('role') || 'button');
    let label = (el.getAttribute('aria-label') || '').trim();
    if (!label && el.labels && el.labels[0]) label = el.labels[0].innerText.trim();
    if (!label && kind !== 'input' && kind !== 'textarea') label = (el.innerText || '').trim();
    if (!label) label = el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('name') || '';
    if (!label && el.querySelector) { const img = el.querySelector('img[alt]'); if (img) label = img.alt; }
    label = String(label).replace(/\s+/g, ' ').slice(0, 50);
    const id = 'e' + (++n);
    el.setAttribute('data-sqa', id);
    window.__sqaTagged.push(el);
    const f = el.form || (el.closest && el.closest('form'));
    let group = '';
    if (f) group = 'f' + Array.from(document.forms).indexOf(f);
    else if (el.getRootNode() instanceof ShadowRoot) group = 's:' + el.getRootNode().host.tagName.toLowerCase();
    out.push({
      id, kind, tag, type, label, selector: __sqaSel(el),
      inView: row.inView, covered: row.covered, disabled: !!el.disabled,
      href: tag === 'a' ? el.href : '', group,
      submit: tag === 'button' ? (type === 'submit' || (!type && !!f)) : type === 'submit',
      options: tag === 'select' ? el.options.length : 0,
      value: (tag === 'input' || tag === 'textarea') ? String(el.value || '').length : 0,
    });
  }
  const heads = Array.from(document.querySelectorAll('h1,h2,h3')).slice(0, 6)
                  .map(h => (h.innerText || '').trim().slice(0, 60)).filter(Boolean);
  return {
    url: location.href, title: (document.title || '').slice(0, 80), heads,
    scrollY: Math.round(scrollY), scrollH: document.documentElement.scrollHeight, vh, vw,
    modal: !!document.querySelector('[role=dialog],[aria-modal=true],dialog[open],.modal'),
    elements: out, links: Array.from(links).slice(0, 400),
  };
}
"""


async def snapshot(page, max_elements: int = 60) -> dict:
    return await page.evaluate(SNAPSHOT_JS, max_elements)

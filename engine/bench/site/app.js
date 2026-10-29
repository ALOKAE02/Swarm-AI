// Acme Store: a hash-routed SPA with 12 planted bugs (B1-B12, see bench/score.py).
const app = document.getElementById('app');
let user = null;            // nobody ever logs in
const cart = [];
let pending = null;
let modalEl = null;
let feedPage = 0, feedLoading = false;

const ROUTES = {
  '/': home, '/shop': shop, '/pricing': pricing, '/signup': signup, '/search': search,
  '/profile': profile, '/feed': feed, '/settings': settings, '/about': about, '/reports': reports,
};
const NAV = [['/', 'Home'], ['/shop', 'Shop'], ['/pricing', 'Pricing'], ['/signup', 'Sign up'],
             ['/search', 'Search'], ['/profile', 'Profile'], ['/feed', 'Feed'], ['/settings', 'Settings'],
             ['/about', 'About']];

function shell(path) {
  return `
  <header>
    <span class="brand">Acme Store <span class="badge" id="cart-count">${cart.length}</span></span>
    <nav id="nav">
      <button id="menu-toggle" aria-label="Menu">&#9776;</button>
      <div class="links">${NAV.map(([p, l]) => `<a href="#${p}" class="${p === path ? 'active' : ''}">${l}</a>`).join('')}</div>
    </nav>
  </header>
  <main id="main"></main>
  <footer><main><p>Get deals in your inbox:</p><sqa-newsletter></sqa-newsletter></main></footer>`;
}

function render() {
  const path = location.hash.replace(/^#/, '') || '/';
  const view = ROUTES[path] || notFound;
  if (view === profile && !user) {          // B8: no logged-out state -> white screen, no error at all
    app.innerHTML = '';
    return;
  }
  app.innerHTML = shell(path);
  document.getElementById('menu-toggle').onclick = () => document.getElementById('nav').classList.toggle('open');
  view(document.getElementById('main'));
}

function home(el) {
  el.innerHTML = `<h1>Welcome to Acme</h1><p>Shoes for every terrain.</p>
    <div class="grid">
      <div class="card"><h3>New arrivals</h3><a href="#/shop">Browse the shop</a></div>
      <div class="card"><h3>Community</h3><a href="#/feed">Read the feed</a></div>
      <div class="card"><h3>Plans</h3><a href="#/pricing">See pricing</a></div>
    </div>`;
}

function shop(el) {
  el.innerHTML = '<h1>Shop</h1><p>Loading products...</p>';
  fetch('/api/products').then(r => r.json()).then(items => {
    if (!el.isConnected) return;
    el.innerHTML = '<h1>Shop</h1><div class="grid" id="products"></div>';
    const grid = el.querySelector('#products');
    items.forEach(p => {
      const c = document.createElement('div');
      c.className = 'card';
      c.innerHTML = `<h3>${p.name}</h3><p>&#8377;${p.price}</p>
        <button class="primary add">Add to cart</button> <button class="quick">Quick view</button>`;
      c.querySelector('.add').onclick = () => addToCart(p.sku);
      c.querySelector('.quick').onclick = () => openQuickView(p);
      grid.appendChild(c);
    });
  });
}

function addToCart(sku) {
  pending = { sku };
  setTimeout(() => {            // B1: double click inside 300ms -> pending is null on the 2nd timer
    cart.push(pending.sku);
    pending = null;
    const b = document.getElementById('cart-count');
    if (b) b.textContent = cart.length;
  }, 300);
}

function openQuickView(p) {
  modalEl = document.createElement('div');
  modalEl.className = 'modal';
  modalEl.innerHTML = `<div class="modal-box"><h3>${p.name}</h3><p>&#8377;${p.price}</p>
    <button class="close-modal">Close</button></div>`;
  document.body.appendChild(modalEl);
  modalEl.querySelector('.close-modal').onclick = () => { modalEl.remove(); modalEl = null; };
  document.addEventListener('keydown', (e) => {   // B2: listener is never removed
    if (e.key === 'Escape') { modalEl.remove(); modalEl = null; }
  });
}

function pricing(el) {
  el.innerHTML = `<h1>Pricing</h1>
    <table class="pricing-table">
      <tr><th>Plan</th><th>Monthly</th><th>Yearly</th><th>Seats</th><th>Support</th></tr>
      <tr><td>Starter</td><td>&#8377;499</td><td>&#8377;4,999</td><td>3</td><td>Email</td></tr>
      <tr><td>Team</td><td>&#8377;1,499</td><td>&#8377;14,999</td><td>15</td><td>Chat</td></tr>
    </table>
    <div class="compare-scroll"><div class="wide">Feature comparison (scroll sideways on purpose) &rarr;</div></div>`;
}   // B3: the table has min-width 720px -> horizontal overflow on phones

function signup(el) {
  el.innerHTML = `<h1>Create account</h1>
    <form id="signup-form" novalidate>
      <div class="row"><label for="name">Name</label><input id="name" name="name"></div>
      <div class="row"><label for="email">Email</label><input id="email" name="email"></div>
      <div class="row"><label for="plan">Plan</label>
        <select id="plan" name="plan"><option>Starter</option><option>Team</option><option>Enterprise</option></select></div>
      <div class="row"><label><input type="checkbox" id="terms"> I accept the terms</label></div>
      <button class="primary" type="submit">Create account</button>
      <p id="signup-msg"></p>
    </form>`;
  el.querySelector('#signup-form').onsubmit = (e) => {
    e.preventDefault();
    const body = JSON.stringify({ name: el.querySelector('#name').value, email: el.querySelector('#email').value });
    fetch('/api/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
      .then(r => r.json())                                        // B4: no error handling at all
      .then(d => { el.querySelector('#signup-msg').textContent = d.message.toUpperCase(); });
  };
}

function search(el) {
  el.innerHTML = `<h1>Search</h1><input id="q" placeholder="Search products" aria-label="Search">
    <div id="results"></div>`;
  el.querySelector('#q').addEventListener('input', (e) => {
    const q = e.target.value;
    el.querySelector('#results').innerHTML = q ? `<p>Results for <b>${q}</b></p>` : '';   // B7: XSS via innerHTML
  });
}

function profile(el) {
  el.innerHTML = `<h1>${user.name}</h1>`;
}

function feed(el) {
  feedPage = 0; feedLoading = false;
  el.innerHTML = '<h1>Community feed</h1><div id="posts"></div><p id="feed-end">Loading more...</p>';
  loadFeed();
}

function loadFeed() {
  if (feedLoading) return;
  feedLoading = true;
  feedPage += 1;
  fetch('/api/feed?page=' + feedPage).then(r => r.json()).then(d => {   // B10: page 3 is malformed, no catch
    const posts = document.getElementById('posts');
    if (!posts) return;
    d.items.forEach(it => {
      const p = document.createElement('div');
      p.className = 'post';
      p.textContent = it.title;
      posts.appendChild(p);
    });
    feedLoading = false;
  });
}

window.addEventListener('scroll', () => {
  if (location.hash !== '#/feed') return;
  if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 250) loadFeed();
});

function settings(el) {
  el.innerHTML = `<h1>Settings</h1>
    <div class="row"><label><input type="checkbox" id="dark"> Dark mode</label></div>
    <div class="row"><label><input type="checkbox" id="notify" checked> Email notifications</label></div>
    <p><a href="#/reports">Generate account reports &rarr;</a></p>`;
  el.querySelector('#dark').onchange = () => {
    console.error("Theme 'dark' not found in registry");   // B11: logged error, feature silently broken
  };
}

function about(el) {
  el.innerHTML = `<h1>About us</h1><img src="/img/team.png" alt="Our team" width="320" height="180">
    <p>We have been making shoes since 1999.</p>`;   // B12: broken image
}

function reports(el) {
  el.innerHTML = `<h1>Reports</h1><button class="primary" id="gen">Generate report</button><p id="rep"></p>`;
  el.querySelector('#gen').onclick = () => {
    const end = Date.now() + 8000;          // B9: 8 seconds of synchronous work freezes the tab
    while (Date.now() < end) { /* crunch */ }
    el.querySelector('#rep').textContent = 'Report ready.';
  };
}

function notFound(el) {
  el.innerHTML = '<h1>Page not found</h1><a href="#/">Go home</a>';
}

class Newsletter extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const s = this.attachShadow({ mode: 'open' });
    s.innerHTML = `<style>.nl{display:flex;gap:8px}input,button{font:inherit;padding:6px 10px}</style>
      <div class="nl"><input placeholder="you@example.com" aria-label="Newsletter email"><button>Join</button></div>`;
    s.querySelector('button').onclick = () => {
      const v = s.querySelector('input').value;
      if (!v) { s.querySelector('.msg').textContent = 'Email required'; return; }   // B6: .msg never rendered
      s.querySelector('input').value = '';
    };
  }
}
customElements.define('sqa-newsletter', Newsletter);

const banner = document.getElementById('cookie-banner');
try { if (localStorage.getItem('cookies-ok')) banner.classList.add('hidden'); } catch (e) {}
document.getElementById('cookie-accept').onclick = () => {
  banner.classList.add('hidden');
  try { localStorage.setItem('cookies-ok', '1'); } catch (e) {}
};

console.warn('[acme] analytics disabled in dev');   // a warning, not an error
window.addEventListener('hashchange', render);
render();

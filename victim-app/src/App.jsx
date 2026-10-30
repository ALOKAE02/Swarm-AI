import { useCallback, useState } from 'react'
import { products } from './data/products'
import { ProductCard } from './components/ProductCard'
import { ProductPanel } from './components/ProductPanel'
import { Checkout } from './components/Checkout'

export default function App() {
  const [selectedId, setSelectedId] = useState(products[0].id)
  const [bagCount, setBagCount] = useState(0)
  const selected = products.find((p) => p.id === selectedId) ?? products[0]
  const onBagChange = useCallback((n) => setBagCount(n), [])

  function select(id) {
    setSelectedId(id)
    // The product view sits above the list: if it has scrolled away, bring it back.
    const detail = document.getElementById('detail')
    if (detail && detail.getBoundingClientRect().top < 0) {
      const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      detail.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
    }
  }

  return (
    <div className="page">
      <header className="topbar">
        <div className="wrap topbar-inner">
          <a className="brand" href="#top" aria-label="Aangan, home">Aangan</a>
          <nav className="nav" aria-label="Main">
            <a href="#shop">Shop</a>
            <a href="#checkout">
              Bag{bagCount > 0 && <span className="nav-count">{bagCount}</span>}
            </a>
          </nav>
        </div>
      </header>

      <main className="wrap main" id="top">
        <section className="intro">
          <h1>Three pieces for the desk and the sofa, made in small batches.</h1>
          <p className="lede">
            Every piece is numbered and ships from the workshop that made it. When a batch is gone, it is gone.
          </p>
        </section>

        <div className="shop" id="shop">
          <ProductPanel key={selected.id} product={selected} onBagChange={onBagChange} />
          <h2 className="list-title">All pieces</h2>
          <div className="product-grid">
            {products.map((p) => (
              <ProductCard key={p.id} product={p} selected={p.id === selected.id} onSelect={select} />
            ))}
          </div>
        </div>

        <div id="checkout">
          <Checkout product={selected} count={bagCount} />
        </div>
      </main>

      <footer className="wrap">
        <div className="footer">
          <span>Aangan</span>
          <span>Questions? hello@aangan.example</span>
        </div>
      </footer>
    </div>
  )
}

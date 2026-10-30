import { useState } from 'react'
import { placeOrder } from '../api/orders'
import { formatPrice } from '../data/products'

export function Checkout({ product, count = 0 }) {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState('idle')

  function onSubmit(event) {
    event.preventDefault()
    setStatus('placing')
    placeOrder({ email }).then(() => setStatus('placed'))
  }

  return (
    <section className="checkout" aria-label="Checkout">
      <div className="checkout-intro">
        <h2 className="section-title">Checkout</h2>
        {count > 0 && product ? (
          <p className="summary">
            <span>
              {product.name}, {count} {count === 1 ? 'piece' : 'pieces'}
            </span>
            <strong>{formatPrice(product.price * count)}</strong>
          </p>
        ) : (
          <p className="muted">Your bag is empty. Add a piece above to check out.</p>
        )}
        <p className="muted small">Free delivery across India. Receipt and tracking go to your email.</p>
      </div>
      <form id="checkout-form" className="checkout-form" onSubmit={onSubmit}>
        <label className="field">
          <span>Email</span>
          <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email" required />
        </label>
        <button id="place-order" type="submit" className="btn btn-primary" disabled={status === 'placing'} aria-busy={status === 'placing'}>
          {status === 'placing' ? <><span className="spinner" aria-hidden="true" />Placing order…</> : 'Place order'}
        </button>
        {status === 'placed' && <p className="ok">Order placed. Check your inbox.</p>}
      </form>
    </section>
  )
}

import { useEffect, useState } from 'react'
import { formatPrice } from '../data/products'
import { ProductArt } from './ProductArt'

export function ProductPanel({ product, onBagChange }) {
  const [cart, setCart] = useState([])
  const left = product.units.length - cart.length

  useEffect(() => {
    onBagChange?.(cart.length)
  }, [cart.length, onBagChange])

  function onBuy() {
    const unit = product.units[cart.length]
    setCart((items) => [...items, unit])
  }

  return (
    <section className="panel" id="detail" aria-label="Product details">
      <ProductArt id={product.id} size="lg" />
      <div className="panel-body">
        <p className="panel-category">{product.category}</p>
        <h2 className="panel-title">{product.name}</h2>
        <p className="panel-blurb">{product.blurb}</p>
        <dl className="specs">
          {product.details.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
        <div className="panel-row">
          <span className="panel-price">{formatPrice(product.price)}</span>
          <span className={`stock${left > 0 ? '' : ' is-out'}`}>
            {left > 0 ? `${left} left` : 'Sold out'}
          </span>
        </div>
        <button id="buy" type="button" className="btn btn-primary" onClick={onBuy}>
          {left > 0 ? 'Add to bag' : 'Sold out'}
        </button>
        <div className="cart" aria-live="polite">
          <div className="cart-head">
            <span>Your bag</span>
            <span key={cart.length} className="cart-count">
              {cart.length === 0 ? 'Empty' : `${cart.length} ${cart.length === 1 ? 'piece' : 'pieces'}`}
            </span>
          </div>
          <ul className="cart-lines">
            {cart.map((unit) => (
              <li key={unit.id}>
                <span>Piece {unit.sku.slice(-2)}</span>
                <span>{formatPrice(product.price)}</span>
              </li>
            ))}
          </ul>
          {cart.length > 0 && (
            <div className="cart-total">
              <span>Subtotal</span>
              <span>{formatPrice(product.price * cart.length)}</span>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

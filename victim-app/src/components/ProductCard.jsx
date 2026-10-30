import { formatPrice } from '../data/products'
import { ProductArt } from './ProductArt'
import './ProductCard.css'

export function ProductCard({ product, selected, onSelect }) {
  return (
    <button
      type="button"
      className={`product-card${selected ? ' is-selected' : ''}`}
      onClick={() => onSelect(product.id)}
      aria-pressed={selected}
    >
      <ProductArt id={product.id} size="sm" />
      <span className="product-row">
        <span className="product-title">{product.name}</span>
        <span className="product-price">{formatPrice(product.price)}</span>
      </span>
      <span className="product-meta">{product.category}</span>
    </button>
  )
}

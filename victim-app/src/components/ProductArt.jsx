// Hand-drawn product illustrations. Each object sits on a backdrop in its own
// material colour: brushed aluminium, notebook sage, undyed wool.

function Lamp() {
  return (
    <svg viewBox="0 0 400 300" role="img" aria-label="Aero Desk Lamp">
      <defs>
        <linearGradient id="lamp-glow" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffe6ad" stopOpacity="0.95" />
          <stop offset="1" stopColor="#ffe6ad" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="lamp-arm" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#d5dbe0" />
          <stop offset="1" stopColor="#9aa6b0" />
        </linearGradient>
      </defs>
      <path className="art-glow" d="M268 152 L322 134 L392 262 L196 262 Z" fill="url(#lamp-glow)" />
      <ellipse cx="292" cy="262" rx="78" ry="7" fill="#ffd98a" opacity="0.45" />
      <ellipse cx="150" cy="264" rx="70" ry="7" fill="#1e2b33" opacity="0.12" />
      <rect x="100" y="246" width="104" height="16" rx="8" fill="#8a96a1" />
      <rect x="106" y="246" width="92" height="4" rx="2" fill="#c9d1d7" />
      <path d="M152 248 L206 138" stroke="url(#lamp-arm)" strokeWidth="11" strokeLinecap="round" />
      <path d="M206 138 L282 96" stroke="url(#lamp-arm)" strokeWidth="9" strokeLinecap="round" />
      <circle cx="152" cy="246" r="8" fill="#6f7c88" />
      <circle cx="206" cy="138" r="9" fill="#6f7c88" />
      <circle cx="206" cy="138" r="3" fill="#c9d1d7" />
      <circle cx="282" cy="96" r="7" fill="#6f7c88" />
      <path d="M276 84 L296 76 L330 132 Q300 150 266 150 Z" fill="#26323b" />
      <path d="M276 84 L296 76 L302 86 L282 94 Z" fill="#3b4954" />
      <path d="M268 151 Q300 150 326 136" stroke="#fff3cf" strokeWidth="4" strokeLinecap="round" fill="none" />
    </svg>
  )
}

function Notebooks() {
  const book = (x, y, rot, cover, spine, extra) => (
    <g transform={`rotate(${rot} ${x + 62} 240)`}>
      <rect x={x + 6} y={y - 4} width="118" height="176" rx="5" fill="#f4f1e8" />
      <rect x={x} y={y} width="124" height="176" rx="6" fill={cover} />
      <rect x={x} y={y} width="12" height="176" rx="4" fill={spine} />
      {extra}
    </g>
  )
  return (
    <svg viewBox="0 0 400 300" role="img" aria-label="Fieldnote Notebook Set">
      <ellipse cx="204" cy="252" rx="118" ry="9" fill="#25301f" opacity="0.13" />
      {book(108, 66, -10, '#3f5b77', '#33495f')}
      {book(140, 60, -1, '#c79d6e', '#ad8459')}
      {book(172, 70, 9, '#8fa68b', '#7a9077', (
        <>
          <rect x="198" y="96" width="62" height="34" rx="3" fill="#f4f1e8" />
          <rect x="206" y="106" width="40" height="3" rx="1.5" fill="#8fa68b" />
          <rect x="206" y="116" width="28" height="3" rx="1.5" fill="#b9c7b6" />
          <rect x="272" y="66" width="7" height="184" rx="3" fill="#232925" />
        </>
      ))}
    </svg>
  )
}

function Throw() {
  return (
    <svg viewBox="0 0 400 300" role="img" aria-label="Merino wool throw">
      <ellipse cx="206" cy="258" rx="140" ry="9" fill="#3a2e1f" opacity="0.12" />
      <path d="M78 206 Q78 186 98 186 L318 186 Q338 186 338 206 L338 238 Q338 256 318 256 L98 256 Q78 256 78 238 Z" fill="#d9cbb3" />
      <path d="M78 220 L338 220" stroke="#c7b79c" strokeWidth="3" />
      <path d="M96 140 Q96 120 116 120 L304 120 Q324 120 324 140 L324 172 Q324 190 304 190 L116 190 Q96 190 96 172 Z" fill="#e9dfcd" />
      <path d="M96 154 L324 154" stroke="#d8cab2" strokeWidth="3" />
      {Array.from({ length: 9 }, (_, i) => (
        <path key={`w${i}`} d={`M100 ${128 + i * 7} L320 ${128 + i * 7}`} stroke="#d3c4aa" strokeWidth="1" opacity="0.55" />
      ))}
      {Array.from({ length: 8 }, (_, i) => (
        <path key={`v${i}`} d={`M84 ${194 + i * 7.5} L332 ${194 + i * 7.5}`} stroke="#c4b393" strokeWidth="1" opacity="0.5" />
      ))}
      <path d="M104 124 Q210 116 316 124" stroke="#f6efe2" strokeWidth="3" strokeLinecap="round" fill="none" />
      <path d="M86 190 Q208 182 330 190" stroke="#e8dcc6" strokeWidth="3" strokeLinecap="round" fill="none" />
      {[0, 1].map((i) => (
        <g key={i}>
          <rect x={132 + i * 150} y="120" width="6" height="70" fill="#8a7458" opacity="0.85" />
          <rect x={144 + i * 150} y="120" width="3" height="70" fill="#8a7458" opacity="0.6" />
          <rect x={118 + i * 160} y="186" width="6" height="70" fill="#7a654b" opacity="0.8" />
        </g>
      ))}
      {Array.from({ length: 9 }, (_, i) => (
        <path key={i} d={`M${100 + i * 6} 190 q-2 14 1 22`} stroke="#c9b897" strokeWidth="2.5" strokeLinecap="round" fill="none" />
      ))}
    </svg>
  )
}

const ART = { p1: Lamp, p2: Notebooks, p3: Throw }
const TONE = { p1: 'tone-alu', p2: 'tone-sage', p3: 'tone-wool' }

export function ProductArt({ id, size = 'sm' }) {
  const Art = ART[id] ?? Lamp
  return (
    <span className={`art art-${size} ${TONE[id] ?? 'tone-alu'}`}>
      <Art />
    </span>
  )
}

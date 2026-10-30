export const products = [
  {
    id: 'p1',
    name: 'Aero Desk Lamp',
    category: 'Lighting',
    price: 2499,
    blurb: 'Brushed aluminium arm, warm 2700K light, one-touch dimmer.',
    details: [
      ['Material', 'Aluminium, cotton cord'],
      ['Size', '46 cm at full reach'],
      ['Made in', 'Pune'],
    ],
    units: [
      { id: 'u-101', sku: 'AERO-LAMP-01' },
      { id: 'u-102', sku: 'AERO-LAMP-02' },
      { id: 'u-103', sku: 'AERO-LAMP-03' },
    ],
  },
  {
    id: 'p2',
    name: 'Fieldnote Notebook Set',
    category: 'Stationery',
    price: 699,
    blurb: 'Three dot-grid notebooks with lay-flat binding.',
    details: [
      ['Paper', '120 gsm cotton rag'],
      ['Size', 'A5, 96 pages each'],
      ['Made in', 'Jaipur'],
    ],
    units: [
      { id: 'u-201', sku: 'FIELD-NB-01' },
      { id: 'u-202', sku: 'FIELD-NB-02' },
      { id: 'u-203', sku: 'FIELD-NB-03' },
    ],
  },
  {
    id: 'p3',
    name: 'Handwoven Merino Wool Throw Blanket, Limited Monsoon Edition',
    category: 'Home',
    price: 5899,
    blurb: 'Loomed in Kullu from undyed merino. Each one is slightly different.',
    details: [
      ['Wool', 'Undyed merino'],
      ['Size', '130 × 180 cm'],
      ['Made in', 'Kullu'],
    ],
    units: [
      { id: 'u-301', sku: 'MERINO-THROW-01' },
      { id: 'u-302', sku: 'MERINO-THROW-02' },
      { id: 'u-303', sku: 'MERINO-THROW-03' },
    ],
  },
]

export const formatPrice = (rupees) => `₹${rupees.toLocaleString('en-IN')}`

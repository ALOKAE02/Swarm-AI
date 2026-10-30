const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export async function placeOrder(order) {
  await wait(400)
  const res = await fetch('/api/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(order),
  })
  if (!res.ok) {
    throw new Error(`Order service responded ${res.status}`)
  }
  return res.json()
}

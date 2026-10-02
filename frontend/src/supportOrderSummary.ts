import type { SupportEvidence } from './supportTypes'

export function formatSupportDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(date)
}

export function supportOrderSummary(evidence: SupportEvidence[], orderId: string) {
  for (const source of evidence) {
    if (source.kind !== 'order' || source.source_id !== orderId) continue
    try {
      const order = JSON.parse(source.text)
      if (order.order_id !== orderId || !Array.isArray(order.lines) || !order.lines.length) continue
      if (!order.lines.every((line: { product_name?: unknown; quantity?: unknown; unit_price_cents?: unknown }) =>
        typeof line.product_name === 'string' && line.product_name.trim() && Number.isInteger(line.quantity) && Number(line.quantity) > 0 && Number.isInteger(line.unit_price_cents) && Number(line.unit_price_cents) >= 0)) continue
      return {
        items: order.lines.map((line: { product_name: string; quantity: number }) => `${line.quantity} × ${line.product_name}`) as string[],
        placedOn: typeof order.placed_on === 'string' ? formatSupportDate(order.placed_on) : null,
        total: new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(order.lines.reduce((sum: number, line: { quantity: number; unit_price_cents: number }) => sum + line.quantity * line.unit_price_cents, 0) / 100),
      }
    } catch { /* Only structured evidence for this exact order can identify the proposal. */ }
  }
  return null
}

import type { EvidenceItem } from './types'

const LEGACY_BOILERPLATE = new Set([
  'Document searches expose at most three ranked passages per tool call.',
  'Web publication times are provider estimates; extracted pages reflect retrieval-time content.',
  'Current Yahoo snapshot fields are used only for company identity, not cited as historical financial evidence.',
  'Daily close prices on the as-of date are excluded because their intraday availability is unknown.',
])

export function visibleResearchLimitations(limitations: string[]): string[] {
  return limitations.filter((item) => !LEGACY_BOILERPLATE.has(item))
}

export function citationKeyword(evidence: EvidenceItem): string {
  if (evidence.evidence_type === 'financial') {
    const field = 'field_path' in evidence && evidence.field_path
      ? evidence.field_path.split('.').at(-1) ?? 'Financial value'
      : 'Financial value'
    const metric = field.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ')
    const year = 'period_end' in evidence && evidence.period_end
      ? ` FY${evidence.period_end.slice(0, 4)}` : ''
    return `${metric}${year}`
  }
  if ('document_type' in evidence && evidence.document_type === 'filing') {
    const form = evidence.title.match(/\b10-[KQ]\b/i)?.[0]?.toUpperCase()
    return form ? `SEC ${form}` : 'SEC filing'
  }
  if (evidence.url) {
    try {
      return new URL(evidence.url).hostname.replace(/^www\./, '')
    } catch { /* Use the source title below. */ }
  }
  return evidence.title || 'Article'
}

export function sourceCount(evidence: EvidenceItem[]): number {
  return new Set(evidence.map((item) => item.reference_id)).size
}

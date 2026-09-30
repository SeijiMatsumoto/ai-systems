import { useEffect, type ReactNode } from 'react'

export interface CitationTooltipMetadata {
  label?: string
  value: string
  href?: string
  code?: boolean
}

interface CitationTooltipProps {
  label: string
  sourceTitle: string
  excerpt: string
  metadata?: CitationTooltipMetadata[]
  className?: string
}

export function CitationTooltip({
  label,
  sourceTitle,
  excerpt,
  metadata = [],
  className = '',
}: CitationTooltipProps) {
  return (
    <details className={`citation-chip ${className}`.trim()}>
      <summary>{label}</summary>
      <div className="citation-tooltip" role="tooltip">
        <strong>{sourceTitle}</strong>
        <blockquote>{excerpt}</blockquote>
        {metadata.length > 0 && <div className="citation-tooltip-meta">
          {metadata.map((item, index) => {
            const content = item.label ? `${item.label} ${item.value}` : item.value
            if (item.href) {
              return <a href={item.href} target="_blank" rel="noreferrer" key={`${content}-${index}`}>{content}</a>
            }
            if (item.code) return <code key={`${content}-${index}`}>{content}</code>
            return <span key={`${content}-${index}`}>{content}</span>
          })}
        </div>}
      </div>
    </details>
  )
}

export function CitationTooltipProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    const closeOutside = (event: PointerEvent | FocusEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      document.querySelectorAll<HTMLDetailsElement>('.citation-chip[open]').forEach((chip) => {
        if (!chip.contains(target)) chip.open = false
      })
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      document.querySelectorAll<HTMLDetailsElement>('.citation-chip[open]').forEach((chip) => {
        chip.open = false
        if (chip.contains(document.activeElement)) (document.activeElement as HTMLElement).blur()
      })
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('focusin', closeOutside)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('focusin', closeOutside)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [])

  return children
}

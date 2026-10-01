import { createPortal } from 'react-dom'
import { useEffect, useId, useLayoutEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'

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
  const ownerId = useId()
  const tooltipId = `${ownerId}-tooltip`
  const chipRef = useRef<HTMLDetailsElement>(null)
  const summaryRef = useRef<HTMLElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const closeTimer = useRef<number | undefined>(undefined)
  const [isOpen, setIsOpen] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  const [position, setPosition] = useState<{ top: number; left: number; width: number } | null>(null)
  const visible = isOpen || hovered || focused

  const cancelClose = () => {
    if (closeTimer.current !== undefined) window.clearTimeout(closeTimer.current)
    closeTimer.current = undefined
  }
  const scheduleClose = () => {
    cancelClose()
    closeTimer.current = window.setTimeout(() => {
      if (chipRef.current?.open) return
      setHovered(false)
      setFocused(false)
    }, 140)
  }
  const enterTooltip = (_event: PointerEvent<HTMLDivElement>) => {
    cancelClose()
    setHovered(true)
  }

  useLayoutEffect(() => {
    if (!visible) {
      setPosition(null)
      return
    }
    const placeTooltip = () => {
      const anchor = summaryRef.current
      const tooltip = tooltipRef.current
      if (!anchor || !tooltip) return
      const margin = 12
      const width = Math.min(390, window.innerWidth - margin * 2)
      const anchorRect = anchor.getBoundingClientRect()
      tooltip.style.width = `${width}px`
      const height = tooltip.getBoundingClientRect().height
      const left = Math.min(Math.max(margin, anchorRect.left), window.innerWidth - width - margin)
      const below = window.innerHeight - anchorRect.bottom - margin
      const above = anchorRect.top - margin
      const top = below >= height || below >= above
        ? Math.min(anchorRect.bottom + 8, window.innerHeight - height - margin)
        : Math.max(margin, anchorRect.top - height - 8)
      setPosition({ top, left, width })
    }
    placeTooltip()
    window.addEventListener('resize', placeTooltip)
    window.addEventListener('scroll', placeTooltip, true)
    return () => {
      window.removeEventListener('resize', placeTooltip)
      window.removeEventListener('scroll', placeTooltip, true)
    }
  }, [visible, sourceTitle, excerpt, metadata.length])

  useEffect(() => () => cancelClose(), [])

  return (
    <details
      ref={chipRef}
      className={`citation-chip ${className}`.trim()}
      data-citation-owner={ownerId}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
      onPointerEnter={() => { cancelClose(); setHovered(true) }}
      onPointerLeave={() => { if (!isOpen) scheduleClose() }}
      onFocusCapture={() => setFocused(true)}
      onBlurCapture={(event) => {
        const next = event.relatedTarget
        if (next instanceof Element && next.closest(`[data-citation-tooltip-owner="${ownerId}"]`)) return
        setFocused(false)
      }}
      onKeyDown={(event) => {
        if (event.key !== 'Escape') return
        cancelClose()
        setHovered(false)
        setFocused(false)
        if (chipRef.current) chipRef.current.open = false
      }}
    >
      <summary ref={summaryRef} aria-controls={tooltipId} aria-describedby={visible ? tooltipId : undefined} aria-expanded={visible}>{label}</summary>
      {visible && createPortal(<div
        ref={tooltipRef}
        id={tooltipId}
        className="citation-tooltip citation-tooltip-portal"
        role="tooltip"
        data-citation-tooltip-owner={ownerId}
        style={{ top: position?.top ?? 0, left: position?.left ?? 0, width: position?.width, visibility: position ? 'visible' : 'hidden' }}
        onPointerEnter={enterTooltip}
        onPointerLeave={() => { if (!isOpen) scheduleClose() }}
        onFocusCapture={() => setFocused(true)}
        onBlurCapture={(event) => {
          if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return
          setFocused(false)
        }}
      >
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
      </div>, document.body)}
    </details>
  )
}

export function CitationTooltipProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    const closeOutside = (event: PointerEvent | FocusEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      const tooltipOwner = target instanceof Element
        ? target.closest<HTMLElement>('[data-citation-tooltip-owner]')?.dataset.citationTooltipOwner
        : undefined
      document.querySelectorAll<HTMLDetailsElement>('.citation-chip[open]').forEach((chip) => {
        if (!chip.contains(target) && chip.dataset.citationOwner !== tooltipOwner) chip.open = false
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

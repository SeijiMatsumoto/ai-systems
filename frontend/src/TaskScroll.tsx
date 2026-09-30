import { useLayoutEffect, useRef } from 'react'

import type { TaskTrailItem } from './taskTrail'

export default function TaskScroll({ items, active, className = '' }: {
  items: TaskTrailItem[]
  active: boolean
  className?: string
}) {
  const viewport = useRef<HTMLDivElement>(null)
  const previousKey = useRef<string | null>(null)
  const latest = items.at(-1)

  useLayoutEffect(() => {
    const element = viewport.current
    if (!element || !latest) return
    const changed = previousKey.current !== null && previousKey.current !== latest.key
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    element.scrollTo({
      top: element.scrollHeight - element.clientHeight,
      behavior: active && changed && !reducedMotion ? 'smooth' : 'auto',
    })
    previousKey.current = latest.key
  }, [active, latest])

  return (
    <div className={`task-scroll ${className}`}>
      <span className="task-scroll-heading">{active ? 'Current task' : 'Run outcome'}</span>
      <div className="task-scroll-viewport" ref={viewport} aria-hidden="true">
        <ol className="task-scroll-list">
          {items.map((item, index) => {
            const age = items.length - index - 1
            return (
              <li className={`task-scroll-item task-scroll-age-${Math.min(age, 3)}`} key={item.key}>
                {item.label}
              </li>
            )
          })}
        </ol>
      </div>
      <span className="task-scroll-announcement" role="status" aria-live="polite">{latest?.label}</span>
    </div>
  )
}

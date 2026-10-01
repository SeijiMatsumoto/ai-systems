import { lazy, Suspense, useEffect, useRef } from 'react'

const IncidentSystemDiagram = lazy(() => import('./IncidentSystemDiagram'))
const ResearchSystemDiagram = lazy(() => import('./ResearchSystemDiagram'))
const KnowledgeSystemDiagram = lazy(() => import('./KnowledgeSystemDiagram'))
const PlannedSystemDiagram = lazy(() => import('./PlannedSystemDiagram'))

export default function ArchitectureModal({ systemId, title, availability, onClose }: {
  systemId: string
  title: string
  availability: 'ready' | 'planned'
  onClose: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    dialog.showModal()
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
      if (dialog.open) dialog.close()
    }
  }, [])

  const closeFromBackdrop = (event: React.MouseEvent<HTMLDialogElement>) => {
    if (event.target !== event.currentTarget) return
    const bounds = event.currentTarget.getBoundingClientRect()
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) {
      event.currentTarget.close()
    }
  }

  return (
    <dialog ref={dialogRef} className="architecture-modal" aria-labelledby="architecture-modal-title" onClose={() => { if (!dialogRef.current?.open) onClose() }} onClick={closeFromBackdrop}>
      <div className="architecture-modal-frame">
        <header className="architecture-modal-header">
          <div>
            <span className="section-kicker">{systemId === 'knowledge-action' ? 'System architecture' : `System architecture · ${availability === 'ready' ? 'Runnable demo' : 'Proposed design'}`}</span>
            <h2 id="architecture-modal-title">{title}</h2>
          </div>
          <button className="architecture-modal-close" type="button" onClick={() => dialogRef.current?.close()} autoFocus aria-label="Close architecture diagram">×</button>
        </header>
        <div className="architecture-modal-body">
          {systemId === 'knowledge-action' && <p className="architecture-modal-note">The runnable demo includes indexed knowledge retrieval, cited answers, Jev grounding checks, and an approval-gated mock support task. Persona and approver selection are simulated; task records stay local.</p>}
          {availability === 'planned' && systemId !== 'knowledge-action' && <p className="architecture-modal-note">This diagram shows the intended boundaries. The workflow is an architecture scaffold and is not runnable yet.</p>}
          <Suspense fallback={<p className="architecture-modal-note">Loading diagram…</p>}>
            {systemId === 'incident-investigation' ? <IncidentSystemDiagram /> : systemId === 'research' ? <ResearchSystemDiagram /> : systemId === 'knowledge-action' ? <KnowledgeSystemDiagram /> : <PlannedSystemDiagram systemId={systemId} />}
          </Suspense>
        </div>
      </div>
    </dialog>
  )
}

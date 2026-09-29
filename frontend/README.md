# AI Systems Workbench

The React/Vite interface presents five architecture designs. Incident investigation, coding, internal knowledge + action, and customer support are clearly labeled scaffolds with static flows and proposed inputs/outputs. Research & workflow is the only runnable workspace: it has a request form, cited briefing, filing setup, saved-run history, and verification diagnostics.

```sh
npm ci
npm run dev
```

The research workspace expects the FastAPI app at `backend.main:app` on `http://127.0.0.1:8000` by default. Set `VITE_API_BASE_URL` to change it. The four scaffold pages make no API or model calls. `npm run build` checks TypeScript and creates a static bundle; `npm run lint` runs Oxlint.

See the [repository README](../README.md) for the system map and the [research architecture](../backend/research_workflow/README.md) for runnable prerequisites.

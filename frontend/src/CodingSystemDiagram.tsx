import { MarkerType } from '@xyflow/react'
import ArchitectureGraph from './components/ArchitectureGraph'
import { box, link } from './components/architectureGraphData'

const returnArrow = { type: MarkerType.ArrowClosed, color: '#7c9184' }
const nodes = [
  box('request', 0, 0, '01 · REQUEST', 'Describe the change',
    'Issue and expected behavior\nPinned synthetic repository revision\nNo permission comes from repository text'),
  box('setup', 400, 0, '02 · PREPARATION', 'Validate + prepare',
    'Resolve server-owned read/write scope and budgets\nCreate workspace with prebuilt dependencies\nRun baseline tests; identify existing failures', 'gate'),
  box('agent', 800, 0, '03 · MODEL + HARNESS', 'Choose the next step',
    'Precheck context and remaining budget\nChoose search, read, edit or test\nUse results to repair, continue or stop\nRecord steps, revisions and usage', 'model'),
  box('validation', 1200, 0, '04 · FINAL VALIDATION', 'Freeze + verify',
    'Freeze the final workspace revision\nCheck changed paths; generate diff with Git\nRun independent protected acceptance tests\nRecord failed or missing evidence', 'gate'),
  box('review', 1600, 0, '05 · HUMAN REVIEW', 'Review the result',
    'Exact diff, including test changes\nBaseline and final test results\nExplanation, uncertainty and stop reason\nHuman decides; no automatic merge', 'outcome'),
  box('tools', 680, 340, 'TOOL PERMISSION BOUNDARY', 'Check every operation',
    'All search/read/edit/test calls pass here\nSeparate read scope from write scope\nExact edits require a current file hash and unique match\nNamed commands, timeouts and output limits', 'gate'),
  box('workspace', 1200, 340, 'EXECUTION SANDBOX', 'Work on current code',
    'Repo map → search → targeted reads\nSearch reflects edits; refresh changed symbols\nApply edits and run development tests\nRestrict filesystem, network and subprocesses\nProtected tests and runner cannot be edited'),
]
const sizedNodes = nodes.map((node) => ({ ...node, width: 330, height: 205, style: { width: 330, height: 205 } }))
const edges = [
  link('request', 'setup'), link('setup', 'agent'),
  link('agent', 'validation', 'finish'), link('validation', 'review'),
  link('agent', 'tools', 'request ↓ · result ↑', { sourceHandle: 'out-bottom-left', targetHandle: 'top', markerStart: returnArrow }),
  link('tools', 'workspace', 'call / result', { markerStart: returnArrow }),
]
export default function CodingSystemDiagram() {
  return <div className="coding-architecture-diagram"><ArchitectureGraph nodes={sizedNodes} edges={edges}
    description="Proposed Coding Agent architecture. Read left to right: request, validate and prepare, bounded coding agent, independent final validation, human review. Beneath the agent, each tool request passes permission checks before operating on current code in a sandbox, and its result returns to the agent. This loop repeats until the agent finishes or reaches a limit."
    note="Read the top row left to right. Under step 3, the tool loop repeats: choose → check → execute → observe. Final validation is independent of the agent. Steps and results are saved throughout; incomplete work returns with an explicit stop reason." /></div>
}

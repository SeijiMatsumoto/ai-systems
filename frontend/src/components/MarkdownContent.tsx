import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/** Safe Markdown rendering: raw HTML is not enabled. */
export function MarkdownContent({ children }: { children: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ table: ({ children }) => <div className="markdown-table-scroll" tabIndex={0} role="region" aria-label="Answer table"><table className="markdown-answer-table">{children}</table></div> }}>{children}</ReactMarkdown>
}

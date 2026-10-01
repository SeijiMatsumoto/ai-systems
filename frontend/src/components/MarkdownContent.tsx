import ReactMarkdown from 'react-markdown'

/** Safe Markdown rendering: raw HTML is not enabled. */
export function MarkdownContent({ children }: { children: string }) {
  return <ReactMarkdown>{children}</ReactMarkdown>
}

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Link } from 'react-router-dom'
import policy from '../content/privacy.en.md?raw'

export default function PrivacyPage() {
  return (
    <main style={{ maxWidth: 860, margin: '0 auto', padding: '48px 20px 80px', color: '#f3f4f8', lineHeight: 1.65 }}>
      <p><Link to="/" style={{ color: '#a8a2ff' }}>← ChronoMark</Link></p>
      <article className="privacy-doc">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{policy}</ReactMarkdown>
      </article>
      <style>{`
        .privacy-doc table{border-collapse:collapse;width:100%;margin:16px 0;font-size:14px}
        .privacy-doc th,.privacy-doc td{border:1px solid #2a2c3b;padding:8px 10px;text-align:left;vertical-align:top}
        .privacy-doc th{background:#141420}
        .privacy-doc h2{margin-top:36px}
      `}</style>
    </main>
  )
}

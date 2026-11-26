import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Link } from 'react-router-dom'
import terms from '../content/terms.en.md?raw'

/* The terms had no page around it: light text on whatever background the body
   happened to have, which on this route is the browser's own -- so the page
   looked blank. It now stands on the product's own dark surface, with the
   wordmark the way back and the same type scale as the rest of the site. */

export default function TermsPage() {
  return (
    <div className="privacy-shell">
      <header className="privacy-head">
        <Link to="/" className="privacy-brand">
          CHRONOMARK
        </Link>
        <Link to="/workspaces" className="privacy-back">
          Open the app
        </Link>
      </header>

      <main className="privacy-page">
        <article className="privacy-doc">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{terms}</ReactMarkdown>
        </article>
        <Link to="/" className="privacy-foot-link">
          ← Back to ChronoMark
        </Link>
      </main>

      <style>{`
        .privacy-shell {
          min-height: 100vh;
          background: #0B0B12;
          color: #F3F4F8;
        }
        .privacy-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          max-width: 900px;
          margin: 0 auto;
          padding: 22px 24px 8px;
        }
        .privacy-brand {
          font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
          font-size: 13px;
          font-weight: 600;
          letter-spacing: 0.24em;
          text-transform: uppercase;
          color: #F3F4F8;
          text-decoration: none;
        }
        .privacy-brand:hover { color: #A8A2FF; }
        .privacy-back {
          font-size: 13px;
          color: #A7ACBA;
          text-decoration: none;
          transition: color 160ms ease;
        }
        .privacy-back:hover { color: #F3F4F8; }

        .privacy-page {
          max-width: 900px;
          margin: 0 auto;
          padding: 24px 24px 96px;
        }
        .privacy-doc { font-size: 15px; line-height: 1.75; color: #E7E8F0; }
        .privacy-doc h1,
        .privacy-doc h2,
        .privacy-doc h3 {
          color: #F3F4F8;
          line-height: 1.3;
          margin: 34px 0 12px;
        }
        .privacy-doc h1 { font-size: 26px; margin-top: 8px; }
        .privacy-doc h2 { font-size: 19px; }
        .privacy-doc h3 { font-size: 16px; }
        .privacy-doc p { margin: 0 0 14px; }
        .privacy-doc a { color: #A8A2FF; }
        .privacy-doc strong { color: #F3F4F8; }
        .privacy-doc ul,
        .privacy-doc ol { margin: 0 0 14px; padding-left: 22px; }
        .privacy-doc li { margin: 4px 0; }
        .privacy-doc hr { border: 0; border-top: 1px solid #2A2C3B; margin: 28px 0; }
        .privacy-doc code {
          padding: 1px 5px;
          border-radius: 4px;
          background: #141420;
          font-size: 13px;
          color: #D8D6FF;
        }
        .privacy-doc table {
          border-collapse: collapse;
          width: 100%;
          margin: 16px 0;
          font-size: 14px;
        }
        .privacy-doc th,
        .privacy-doc td {
          border: 1px solid #2A2C3B;
          padding: 8px 10px;
          text-align: left;
          vertical-align: top;
        }
        .privacy-doc th { background: #141420; color: #F3F4F8; }
        .privacy-foot-link {
          display: inline-block;
          margin-top: 36px;
          font-size: 13px;
          color: #A7ACBA;
          text-decoration: none;
        }
        .privacy-foot-link:hover { color: #F3F4F8; }
      `}</style>
    </div>
  )
}

import { FileText } from 'lucide-react'
import '../styles/proxeiro.css'
import '../styles/uploadTheme.css'

/* Documents page.

   Reachable from the command palette ("Upload Documents"). It is deliberately a
   shell for now: the same page surface, hero and card as the video upload, so
   the PDF/PowerPoint/Word pipeline can land here without another redesign. No
   upload wiring yet. */

export default function Documents() {
  return (
    <main className="upload-shell">
      <header className="upload-hero">
        <span className="upload-eyebrow">02 Documents</span>
        <h1>
          Add a document. <em>Ask it anything.</em>
        </h1>
        <p className="upload-subtitle">
          PDF, PowerPoint and Word. The same index that answers about a lecture
          will answer about a handout, citing the page or the slide instead of
          a timestamp. The pipeline is not wired yet.
        </p>
      </header>

      <section className="upload-grid">
        <div className="upload-center-card">
          <div className="upload-dropzone">
            <button className="upload-dropzone-button" type="button" disabled>
              <span className="upload-dropzone-icon" aria-hidden="true">
                <FileText size={30} strokeWidth={1.4} />
              </span>
              <span className="upload-dropzone-title">Documents, coming next</span>
              <span className="upload-dropzone-copy">
                PDF, PPTX and DOCX parsing is the next step. This page exists so
                the route and its shortcut are already in place.
              </span>
            </button>

            <div className="upload-spec" aria-hidden="true">
              <p className="upload-spec-row">
                <span>Parse</span>
                <i />
                <strong>Pdf / Pptx / Docx</strong>
              </p>
              <p className="upload-spec-row">
                <span>Index</span>
                <i />
                <strong>Qdrant - Pages</strong>
              </p>
              <p className="upload-spec-row">
                <span>Answer</span>
                <i />
                <strong>Deepseek - Cited</strong>
              </p>
              <p className="upload-spec-note">Status / awaiting pipeline</p>
            </div>
          </div>
        </div>
      </section>
    </main>
  )
}

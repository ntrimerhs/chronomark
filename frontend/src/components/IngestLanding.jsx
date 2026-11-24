import { useMemo, useRef, useState } from 'react'
import '../styles/ingestLanding.css'

/* The ingestion screen, transcribed from the supplied page.

   Left: the two line headline and the typewriter line with its caret, the copy and
   the divider. Right: the HUD capsule with its corner brackets, the dashed drop
   surface, the file-type pill, the YouTube action, the selected-file row, the Start
   Analysis action and the four node pipeline stepper, with the locked-chat teaser
   underneath.

   It renders the real state it is given: the file name and size, the upload
   percentage, the stage the pipeline is in, and any error. */

const STEPS = ['INPUT', 'EXTRACT', 'INDEX', 'READY']

/* The backend reports preparing -> extracting_audio -> downloading_from_r2 ->
   processing_audio_and_frames -> transcribing_audio -> embedding_text -> finalizing
   -> summarising -> completed. The four nodes fold those into INPUT, EXTRACT, INDEX
   and READY. */
const STAGE_NODE = {
  idle: 0,
  failed: 0,
  preparing: 0,
  queued: 0,
  downloading: 0,
  extracting_audio: 0,
  downloading_from_r2: 0,
  processing_audio_and_frames: 1,
  transcribing_audio: 1,
  chunking: 2,
  reading_figures: 2,
  embedding: 2,
  embedding_text: 2,
  finalizing: 2,
  summarising: 2,
  completed: 3,
}

function stageIndex(stage) {
  return STAGE_NODE[stage] ?? 0
}

export default function IngestLanding({
  file,
  uploadProgress = 0,
  backendProgress = 0,
  stage = 'idle',
  isUploading = false,
  error = '',
  youtubeUrl = '',
  youtubeOpen = false,
  onFileSelected,
  onSubmit,
  onSubmitYoutube,
  onYoutubeUrl,
  onToggleYoutube,
}) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  const active = stageIndex(stage)

  /* The transfer and the backend are two counters, not one: the upload fills the
     first tenth of the bar, then the backend's own percentage takes over, so the
     number and the lit node always describe the same work. */
  const percent = useMemo(() => {
    if (stage === 'completed') return 100
    if (backendProgress > 0) return Math.min(99, Math.round(backendProgress))
    if (uploadProgress > 0) return Math.max(1, Math.round(uploadProgress * 0.1))
    return 0
  }, [backendProgress, stage, uploadProgress])

  const statusLabel = useMemo(() => {
    if (stage === 'failed') return 'FAILED'
    if (stage === 'completed') return 'READY'
    if (!isUploading && stage === 'idle') return 'READY'
    return STEPS[stageIndex(stage)]
  }, [isUploading, stage])

  const sizeLabel = file ? `${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)` : 'No file selected yet'

  return (
    <div className="ing">
      <main className="ing-main">
        <div className="ing-grid">
          <section className="ing-left">
            <div className="ing-headline">
              <h1>
                ADD A<br />RECORDING.
              </h1>
              <div className="ing-type">
                <span className="ing-type-text">ASK IT ANYTHING.</span>
                <span className="ing-caret" aria-hidden="true" />
              </div>
            </div>

            <p className="ing-copy">
              A file from this machine or a YouTube link. The pipeline transcribes it, indexes every
              passage, and hands you the second an answer came from.
            </p>

            <div className="ing-divider" />
          </section>

          <section className="ing-right">
            <div className="ing-card">
              <span className="ing-bracket is-tl" />
              <span className="ing-bracket is-tr" />
              <span className="ing-bracket is-bl" />
              <span className="ing-bracket is-br" />

              <div
                className={`ing-dropzone${dragging ? ' is-dragging' : ''}`}
                role="button"
                tabIndex={0}
                onClick={() => inputRef.current?.click()}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click()
                }}
                onDragEnter={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={(event) => {
                  event.preventDefault()
                  setDragging(false)
                }}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragging(false)
                  onFileSelected?.(event.dataTransfer.files?.[0] ?? null)
                }}
              >
                <div className="ing-icon-wrap">
                  <div className="ing-icon-glow" />
                  <div className="ing-icon">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                      <path
                        d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </div>
                </div>

                <h3 className="ing-drop-title">Drag and drop or click to upload</h3>
                <p className="ing-drop-copy">
                  Supports video files and sends them directly to the backend processing pipeline.
                </p>

                <div className="ing-filetypes">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path
                      d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                  </svg>
                  <span>MP4 · MOV · WEBM · WAV (UP TO 2GB)</span>
                </div>

                <input
                  ref={inputRef}
                  type="file"
                  accept="video/*,audio/*"
                  hidden
                  onChange={(event) => onFileSelected?.(event.target.files?.[0] ?? null)}
                />
              </div>

              <div className="ing-youtube-row">
                <button type="button" className="ing-youtube" onClick={onToggleYoutube}>
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z" />
                  </svg>
                  <span>IMPORT FROM YOUTUBE</span>
                </button>
              </div>

              {youtubeOpen ? (
                <form className="ing-youtube-form" onSubmit={onSubmitYoutube}>
                  <input
                    type="url"
                    value={youtubeUrl}
                    onChange={(event) => onYoutubeUrl?.(event.target.value)}
                    placeholder="Paste a YouTube URL…"
                    autoFocus
                  />
                  <button type="submit">Ingest</button>
                </form>
              ) : null}

              <div className="ing-selected">
                <div className="ing-selected-text">
                  <span className="ing-label">SELECTED FILE</span>
                  <span className={`ing-filename${file ? ' is-set' : ''}`}>{sizeLabel}</span>
                </div>

                <button
                  type="button"
                  className="ing-start"
                  disabled={!file || isUploading}
                  onClick={() => onSubmit?.()}
                >
                  <svg fill="none" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M8.25 4.5l7.5 7.5-7.5 7.5" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" />
                  </svg>
                  <span>START ANALYSIS</span>
                </button>
              </div>

              <div className="ing-status">
                <div className="ing-status-head">
                  <span className="ing-status-name">
                    <i />
                    PROCESS / STATUS
                  </span>
                  <span className="ing-status-value">
                    {percent}% {statusLabel}
                  </span>
                </div>

                <div className="ing-steps">
                  <span className="ing-steps-line" />
                  {STEPS.map((step, index) => (
                    <div
                      key={step}
                      className={`ing-step${index < active ? ' is-done' : ''}${index === active ? ' is-active' : ''}`}
                    >
                      <span className="ing-step-dot">
                        <i />
                      </span>
                      <span className="ing-step-label">{step}</span>
                    </div>
                  ))}
                </div>
              </div>

              {error ? <p className="ing-error">{error}</p> : null}
            </div>

            <div className="ing-teaser">
              <div className="ing-teaser-text">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a.75.75 0 01-1.074-.85 9.948 9.948 0 001.378-3.414C4.168 15.342 3 13.766 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="1.8"
                  />
                </svg>
                <span>Upload a video to unlock the chat panel &amp; temporal citation engine</span>
              </div>
              <div className="ing-teaser-arrow">
                <svg fill="none" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M8.25 4.5l7.5 7.5-7.5 7.5" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                </svg>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}

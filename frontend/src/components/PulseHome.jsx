import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import '../styles/pulseHome.css'

/* The landing page, to the supplied composition.

   Top bar with the reticle mark and telemetry navigation, the orbital hero with
   the giant wordmark over a calibrated reticle, the interactive lecture scanner,
   the temporal architecture cards, the speed comparison and the launch console.

   Everything that looks like a control is one: the navigation scrolls to its
   section, both hero buttons and the console lead into the product, and the
   console accepts a link and hands it to the upload page. The lecture in the
   demo panel is a labelled illustration, not a claim about live content. */

const NAV = [
  { code: '01', label: 'Engine', href: '#demo-lab' },
  { code: '02', label: 'Temporal search', href: '#how-it-works' },
  { code: '03', label: 'Demo lab', href: '#demo-lab' },
  { code: '04', label: 'Benchmarks', href: '#benchmarks' },
]

const HITS = [
  {
    time: '00:42:15',
    tag: 'Derivation',
    tone: 'accent',
    match: 'Match: 99.8%',
    title: 'Derivation of the loss gradient in attention layers',
    quote:
      'β€β€¦if you compute the Jacobian with respect to the query projection, the scaling factor prevents gradient saturationβ€¦β€',
    foot: 'Visual: slide 14 + whiteboard',
    action: 'Jump to frame',
  },
  {
    time: '01:14:22',
    tag: 'Current frame',
    tone: 'success',
    match: '100% confidence',
    title: 'Why the eigenvalues diverge under high learning rates',
    quote:
      'β€β€¦notice how this matrix blows up when the step size violates Lipschitz continuity. Keep this condition in mind for Theorem 3β€¦β€',
    foot: 'Chalkboard: equation 4.2',
    action: 'Playing (00:01:43)',
    active: true,
  },
  {
    time: '02:08:40',
    tag: 'Exam alert',
    tone: 'warn',
    match: 'Match: 97.4%',
    title: 'Midterm hint: question 3 covers this exact theorem',
    quote:
      'β€β€¦will we have to derive the boundary conditions on paper? Yes, specifically the Dirichlet bounds from todayβ€¦β€',
    foot: 'Q&A segment Β· micro-mic',
    action: 'Pin mark',
  },
]

const CARDS = [
  {
    number: '01',
    title: 'Sub-second phonetic anchoring',
    body: 'Pinpoints the exact phoneme even when a speaker mumbles or writes silently, by aligning the raw waveform instead of trusting a transcript.',
    left: 'Latency: 1.2ms',
    right: 'Phoneme resolution β†—',
  },
  {
    number: '02',
    title: 'Multimodal board vision',
    body: 'Reads mathematical notation, matrices and slide transitions as they appear, and keeps them attached to the moment they were drawn.',
    left: 'LaTeX export: native',
    right: 'OCR accuracy 99.4% β†—',
  },
  {
    number: '03',
    title: 'Semantic memory pinning',
    body: 'Ask β€where did he prove lemma 2?β€ or β€when was the lab deadline mentioned?β€ and land on the five-second window that answers it.',
    left: 'Natural query: enabled',
    right: 'Zero-shot leap β†—',
  },
]

export default function PulseHome() {
  const [url, setUrl] = useState('')
  const navigate = useNavigate()

  function launch(event) {
    event.preventDefault()
    navigate('/upload')
  }

  return (
    <div className="pm">
      <header className="pm-bar">
        <div className="pm-brand-wrap">
          <a className="pm-brand" href="/" title="Chronomark home">
            <span className="pm-mark" aria-hidden="true">
              <span className="pm-mark-dot" />
            </span>
            <span>Chronomark</span>
          </a>
          <span className="pm-crumb">
            <i />
            <b>01</b>
            Discover
          </span>
        </div>

        <nav className="pm-nav" aria-label="Sections">
          {NAV.map((item) => (
            <a key={item.label} href={item.href}>
              <span className="pm-nav-code">[{item.code}]</span>
              {item.label}
            </a>
          ))}
        </nav>

        <div className="pm-bar-actions">
          <Link className="pm-search" to="/documents" aria-label="Open document search">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" strokeLinecap="round" />
            </svg>
            <span>Search</span>
            <kbd>βK</kbd>
          </Link>
          <Link className="pm-try" to="/upload">
            Try now <span aria-hidden="true">β†—</span>
          </Link>
        </div>
      </header>

      <section className="pm-hero">
        <div className="pm-hero-halo" aria-hidden="true" />
        <div className="pm-hero-field" aria-hidden="true" />

        <div className="pm-telemetry-left" aria-hidden="true">
          <span className="pm-rule" />
          <span>Time</span>
          <span>Data</span>
          <span>Precision</span>
          <span>Impact</span>
        </div>

        <div className="pm-stamp" aria-hidden="true">
          <span className="pm-rule-short" />
          <span className="pm-dim">T β€”</span>
          <b>00:01:43</b>
        </div>

        <div className="pm-telemetry-right" aria-hidden="true">
          <b>01</b>
          <span className="pm-dim">/</span>
          <span>β</span>
          <span className="pm-rule-mid" />
        </div>

        <div className="pm-status" aria-hidden="true">
          <b>///</b>
          <span>System active Β· latency 4.2ms</span>
        </div>

        <div className="pm-reticle" aria-hidden="true">
          <span className="pm-ring-outer">
            <i className="pm-tick pm-tick-n" />
            <i className="pm-tick pm-tick-s" />
            <i className="pm-tick pm-tick-e" />
            <i className="pm-tick pm-tick-w" />
          </span>
          <span className="pm-ring-dashed" />
          <span className="pm-ring-inner">
            <i className="pm-satellite" />
          </span>
          <span className="pm-ring-dotted" />
          <span className="pm-crosshair">
            <i />
            <i />
            <b />
          </span>
          <span className="pm-orbit">
            <i className="pm-marker">
              <b />
            </i>
          </span>
        </div>

        <div className="pm-hero-copy">
          <h1 className="pm-title">Chronomark</h1>
          <p className="pm-tagline">
            Hours of lecture. One exact <em>moment.</em>
          </p>
          <p className="pm-lede">
            The temporal engine that indexes a four-hour symposium, its phonemes and its board
            notes down to the second, then hands you the moment you asked for.
          </p>

          <div className="pm-hero-actions">
            <Link className="pm-pill" to="/upload">
              Explore the demo <span aria-hidden="true">β†—</span>
            </Link>
            <a className="pm-pill-ghost" href="#how-it-works">
              <span className="pm-play" aria-hidden="true">
                β–¶
              </span>
              How it works
              <span className="pm-mini-wave" aria-hidden="true">
                <i />
                <i />
                <i />
                <i />
              </span>
            </a>
          </div>

          <div className="pm-badges">
            <span>Indexed sources:</span>
            <span>Lecture archives</span>
            <span>Document sets</span>
            <span>Course recordings</span>
            <span>Seminar vaults</span>
          </div>
        </div>
      </section>

      <section className="pm-section pm-demo" id="demo-lab">
        <div className="pm-section-head">
          <div>
            <p className="pm-eyebrow">[03 // Demo lab] β€” Interactive temporal inspection</p>
            <h2 className="pm-h2">Multimodal lecture scanner</h2>
          </div>
          <p className="pm-section-note">
            Query the voice, the board and the slides at the same time. The illustration below shows
            how a hit keeps its frame, its quote and its confidence together.
          </p>
        </div>

        <div className="pm-panel">
          <div className="pm-hud">
            <div className="pm-hud-left">
              <span className="pm-dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              <span className="pm-dim">Session:</span>
              <b>QUANTUM_PHYSICS_LEC19.mp4</b>
            </div>
            <div className="pm-hud-right">
              <span>
                Duration: <b>02:44:18</b>
              </span>
              <span className="pm-chip">Chronomark indexed</span>
            </div>
          </div>

          <div className="pm-split">
            <div className="pm-stage">
              <div className="pm-searchline">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <circle cx="11" cy="11" r="8" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" strokeLinecap="round" />
                </svg>
                <span>derivation of eigenvalues divergence matrix</span>
                <b>3 matches</b>
              </div>

              <div className="pm-board">
                <div className="pm-board-notes" aria-hidden="true">
                  <p className="pm-board-cap">### Section 4.2: tensor eigenvalues ###</p>
                  <p className="pm-board-eq">β‡_ΞΈ L(ΞΈ) = π”Ό [ (y β’ f(x; ΞΈ))αµ€ β€Ά Ξ£β»ΒΉ β€Ά β‚f/β‚ΞΈ ]</p>
                  <p className="pm-board-warn">Ξ»_max (Aαµ€ A) &gt; Ξ³_critical β‡’ divergence at scale</p>
                  <p className="pm-board-cap">Proof continued: lim_{'{'}kβ†’β{'}'} β€–W^{'{'}k+1{'}'} β’ W^{'{'}k{'}'}β€– β‰  0</p>
                </div>

                <div className="pm-board-top">
                  <span className="pm-frame">
                    <i />
                    Frame: 01:14:22.04
                  </span>
                  <span className="pm-chip">Chalkboard OCR: 99.4%</span>
                </div>

                <div className="pm-quote">
                  <div className="pm-quote-head">
                    <b>Eigenvalue proof box</b>
                    <span>Conf: 0.998</span>
                  </div>
                  <p>
                    β€Notice how this matrix blows up when the step size violates Lipschitz
                    continuity.β€
                  </p>
                  <small>Voice: Prof. Strachan Β· chalkboard sync: 0.04s</small>
                </div>

                <div className="pm-board-foot">
                  <span className="pm-time">
                    <i aria-hidden="true">ββ</i>
                    01:14:22
                    <em>/ 02:44:18</em>
                  </span>
                  <span className="pm-live">β— Synchronised</span>
                </div>
              </div>

              <div className="pm-timeline">
                <div className="pm-timeline-head">
                  <span>Temporal phonetic density</span>
                  <b>Pinpoint mark: 01:14:22</b>
                </div>
                <div className="pm-scrub">
                  <div className="pm-wave" aria-hidden="true">
                    {Array.from({ length: 34 }, (_, index) => (
                      <i
                        key={index}
                        className={
                          index % 9 === 5 ? 'is-accent' : index % 11 === 7 ? 'is-warn' : undefined
                        }
                        style={{ height: `${8 + ((index * 7) % 26)}px` }}
                      />
                    ))}
                  </div>
                  <span className="pm-playhead" aria-hidden="true" />
                </div>
              </div>
            </div>

            <aside className="pm-results">
              <div className="pm-results-head">
                <span>
                  <i />
                  Temporal index hits
                </span>
                <b>0.014s search time</b>
              </div>

              {HITS.map((hit) => (
                <article key={hit.time} className={`pm-hit${hit.active ? ' is-active' : ''}`}>
                  <div className="pm-hit-head">
                    <span className={`pm-hit-time is-${hit.tone}`}>
                      {hit.time}
                      <em>{hit.tag}</em>
                    </span>
                    <span className="pm-dim">{hit.match}</span>
                  </div>
                  <h3>{hit.title}</h3>
                  <p>{hit.quote}</p>
                  <div className="pm-hit-foot">
                    <span>{hit.foot}</span>
                    <b>{hit.action}</b>
                  </div>
                </article>
              ))}

              <div className="pm-results-foot">
                <span>Sync drift: &lt; 0.02s</span>
                <span>Export: Anki / Obsidian β†—</span>
              </div>
            </aside>
          </div>
        </div>
      </section>

      <section className="pm-section pm-arch" id="how-it-works">
        <div className="pm-center-head">
          <p className="pm-eyebrow">[02 // Temporal architecture]</p>
          <h2 className="pm-h2">How sub-second retrieval works.</h2>
          <p className="pm-section-note pm-note-center">
            Transcript search makes you fast-forward. Chronomark binds what was said and what was
            drawn to the timeline itself, so an answer is a timestamp you can open.
          </p>
        </div>

        <div className="pm-cards">
          {CARDS.map((card) => (
            <article key={card.number} className="pm-card">
              <span className="pm-card-num">{card.number}</span>
              <h3>{card.title}</h3>
              <p>{card.body}</p>
              <div className="pm-card-foot">
                <span>{card.left}</span>
                <b>{card.right}</b>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="pm-section pm-bench" id="benchmarks">
        <div className="pm-bench-grid">
          <div>
            <p className="pm-eyebrow">[04 // Benchmarks]</p>
            <h2 className="pm-h2">The difference is one question.</h2>
            <p className="pm-section-note">
              Scrubbing through a recording costs minutes per question. Asking it costs seconds, and
              the answer arrives with the frame it came from.
            </p>
            <div className="pm-metrics">
              <div>
                <b>98.4%</b>
                <span>Seek time removed</span>
              </div>
              <div>
                <b>0.02s</b>
                <span>Timestamp drift</span>
              </div>
            </div>
          </div>

          <div className="pm-meter">
            <div className="pm-meter-row">
              <div className="pm-meter-head">
                <span>Manual scrubbing</span>
                <b className="is-warn">Minutes per question</b>
              </div>
              <div className="pm-track">
                <span className="is-slow" style={{ width: '88%' }}>
                  Dragging, 2x speed, missed notes
                </span>
              </div>
            </div>

            <div className="pm-meter-row">
              <div className="pm-meter-head">
                <span>Chronomark</span>
                <b>One jump</b>
              </div>
              <div className="pm-track">
                <span className="is-fast" style={{ width: '14%' }}>
                  1.4s
                </span>
                <em>Exact moment opened</em>
              </div>
            </div>

            <div className="pm-meter-foot">
              <span>Index: lecture audio, board, slides</span>
              <span className="pm-ok">β— Auditable answers</span>
            </div>
          </div>
        </div>
      </section>

      <section className="pm-launch">
        <div className="pm-launch-rings" aria-hidden="true">
          <span />
          <span />
        </div>
        <div className="pm-launch-copy">
          <p className="pm-eyebrow">[Instant extraction]</p>
          <h2 className="pm-h2">
            Stop scrubbing through endless video. <em>Start pinpointing.</em>
          </h2>
          <p className="pm-section-note pm-note-center">
            Open a recording or a document, ask a question in your own words, and keep the part that
            answers it.
          </p>

          <form className="pm-console" onSubmit={launch}>
            <label className="pm-console-field">
              <span>URL:</span>
              <input
                type="text"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://youtube.com/watch?v=β€¦ or a file"
                aria-label="Lecture link"
              />
            </label>
            <button type="submit">
              {url.trim() ? 'Index this lecture β†—' : 'Chronomark lecture β†—'}
            </button>
          </form>

          <div className="pm-console-foot">
            <span>Works with links and files</span>
            <span>Β·</span>
            <span>PDF, PowerPoint, Word, video</span>
            <span>Β·</span>
            <span>Answers cite the page or the moment</span>
          </div>
        </div>
      </section>

      <footer className="pm-footer">
        <div className="pm-footer-grid">
          <div className="pm-footer-brand">
            <span className="pm-brand">
              <span className="pm-mark" aria-hidden="true">
                <span className="pm-mark-dot" />
              </span>
              <span>Chronomark</span>
            </span>
            <p>
              Temporal indexing for lectures, keynotes and documents. Ask a question, get the
              moment.
            </p>
          </div>

          <div className="pm-footer-col">
            <b>Platform</b>
            <a href="#demo-lab">Lecture scanner</a>
            <a href="#how-it-works">Board reading</a>
            <a href="#how-it-works">Audio anchoring</a>
            <Link to="/documents">Documents</Link>
          </div>

          <div className="pm-footer-col">
            <b>Product</b>
            <Link to="/upload">Upload</Link>
            <Link to="/documents">Workspace</Link>
            <a href="#benchmarks">Benchmarks</a>
            <a href="#top">Back to top</a>
          </div>

          <div className="pm-footer-telemetry">
            <div className="pm-footer-telemetry-head">
              <b>System</b>
              <span className="pm-ok">β— Nominal</span>
            </div>
            <div>
              <span>Retrieval latency</span>
              <b>4.2ms avg</b>
            </div>
            <div>
              <span>Languages</span>
              <b>Greek + English</b>
            </div>
            <div>
              <span>Citations</span>
              <b>Page and moment</b>
            </div>
          </div>
        </div>

        <div className="pm-footer-base">
          <span>Β© {new Date().getFullYear()} Chronomark</span>
          <span>Temporal retrieval systems</span>
        </div>
      </footer>
    </div>
  )
}

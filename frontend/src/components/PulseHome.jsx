import { useState } from 'react'
import '../styles/pulseLanding.css'

/* The landing page, transcribed from the supplied markup.

   Same structure, same copy, same numbers: the fixed 64px bar with the reticle
   mark and the telemetry navigation, the orbital hero with its calibrated
   reticle, the lecture scanner panel, the three architecture cards, the speed
   comparison, the launch console and the footer.

   Nothing was redesigned and no claim was softened: the strings are the ones in
   the source. The only adaptation is mechanical, since this project has no
   Tailwind runtime: the utility classes are expressed as scoped CSS rules. */

const NAV = [
  ['[01]', 'ENGINE', '#demo-lab'],
  ['[02]', 'TEMPORAL SEARCH', '#how-it-works'],
  ['[03]', 'DEMO LAB', '#demo-lab'],
  ['[04]', 'BENCHMARKS', '#benchmarks'],
]

const REPOSITORIES = ['MIT OPENCOURSEWARE', 'STANFORD CS ARCHIVES', 'NEURIPS 2024', 'CERN SYMPOSIUMS']

const HITS = [
  {
    time: '00:42:15',
    tag: 'DERIVATION',
    tone: 'accent',
    match: 'MATCH: 99.8%',
    title: 'Derivation of Loss Gradient in Attention Layers',
    quote:
      '"...if you compute the Jacobian with respect to the query projection, you\'ll observe the scaling factor $\\sqrt{d_k}$ prevents gradient saturation..."',
    foot: 'Visual: Slide 14 + Whiteboard',
    action: 'Jump to Frame β†’',
  },
  {
    time: '01:14:22',
    tag: 'CURRENT FRAME',
    tone: 'success',
    match: '100% CONFIDENCE',
    title: 'Why the Eigenvalues Diverge Under High Learning Rates',
    quote:
      '"...notice how this matrix blows up when the step size violates Lipschitz continuity. Keep this exact condition in mind for Theorem 3..."',
    foot: 'Chalkboard: Equation 4.2',
    action: 'PLAYING (00:01:43)',
    active: true,
  },
  {
    time: '02:08:40',
    tag: 'EXAM ALERT',
    tone: 'warn',
    match: 'MATCH: 97.4%',
    title: 'Midterm Hint: Question 3 Covers This Exact Theorem',
    quote:
      '"...student question: will we have to derive the boundary conditions on paper? Professor: Yes, specifically the Dirichlet bounds from today..."',
    foot: 'Q&A Segment β€Ά Micro-mic',
    action: 'Pin Mark +',
  },
]

const CARDS = [
  {
    number: '01',
    title: 'Sub-Second Phonetic Anchoring',
    body: 'Pinpoints exact audio phonemes even when speakers turn their backs to mumble or write silently on the blackboard. Ignores speech-to-text hallucinations through raw waveform alignment.',
    left: 'LATENCY: 1.2ms',
    right: 'PHONEME RESOLUTION β†—',
  },
  {
    number: '02',
    title: 'Multimodal Board Vision',
    body: 'Chalk stroke neural tracking indexes mathematical notation, matrices, chemical diagrams, and PowerPoint slide transitions dynamically as they are drawn in real-time.',
    left: 'LATEX EXPORT: NATIVE',
    right: 'OCR ACCURACY 99.4% β†—',
  },
  {
    number: '03',
    title: 'Semantic Memory Pinning',
    body: 'Ask intuitive human questions like "where did he prove lemma 2?" or "when did the professor mention the lab deadline?" and leap straight to the 5-second video window.',
    left: 'NATURAL QUERY: ENABLED',
    right: 'ZERO-SHOT LEAP β†—',
  },
]

// 30 bars, matching the reference waveform row
const WAVE = [
  3, 5, 2, 7, 4, 6, 8, 5, 3, 6, 8, 4, 7, 5, 8, 6, 3, 7, 4, 8, 6, 3, 5, 7, 2, 6, 8, 5, 4, 7,
]

export default function PulseHome() {
  const [url, setUrl] = useState('')

  return (
    <div className="pulse">
      <header className="pulse-bar">
        <div className="pulse-bar-left">
          <a className="pulse-brand" href="#top" title="Chronomark Home">
            <span className="pulse-mark" aria-hidden="true">
              <i className="pulse-mark-dot" />
            </span>
            <span>CHRONOMARK</span>
          </a>
          <span className="pulse-crumb">
            <i />
            <b>01</b>
            <span>DISCOVER</span>
          </span>
        </div>

        <nav className="pulse-nav" aria-label="Main">
          {NAV.map(([code, label, href]) => (
            <a key={label} href={href}>
              <span className="pulse-nav-code">{code}</span>
              <span>{label}</span>
            </a>
          ))}
        </nav>

        <div className="pulse-bar-actions">
          <a className="pulse-search" href="/documents">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" strokeLinecap="round" />
            </svg>
            <span>SEARCH</span>
            <kbd>⌘K</kbd>
          </a>
          <a className="pulse-try" href="#demo-lab">
            <span>TRY NOW</span>
            <b>β†—</b>
          </a>
        </div>
      </header>

      <main>
        <section className="pulse-hero" id="top">
          <div className="pulse-hero-glow" aria-hidden="true">
            <span className="pulse-glow-core" />
            <span className="pulse-glow-wide" />
          </div>

          <div className="pulse-marks" aria-hidden="true">
            <span className="pulse-marks-rule" />
            <span>TIME</span>
            <span>DATA</span>
            <span>PRECISION</span>
            <span>IMPACT</span>
          </div>

          <div className="pulse-stamp" aria-hidden="true">
            <span className="pulse-stamp-rule" />
            <span className="pulse-faint">T β€”</span>
            <b>00:01:43</b>
          </div>

          <div className="pulse-index" aria-hidden="true">
            <b>01</b>
            <span className="pulse-faint">/</span>
            <span className="pulse-pure">∞</span>
            <span className="pulse-index-rule" />
          </div>

          <div className="pulse-latency" aria-hidden="true">
            <b>///</b>
            <span>SYSTEM ACTIVE β€Ά LATENCY 4.2ms</span>
          </div>

          <div className="pulse-reticle" aria-hidden="true">
            <div className="pulse-ring-outer">
              <span className="pulse-notch is-n" />
              <span className="pulse-notch is-s" />
              <span className="pulse-notch is-e" />
              <span className="pulse-notch is-w" />
              <span className="pulse-slash is-nw" />
              <span className="pulse-slash is-ne" />
              <span className="pulse-slash is-sw" />
              <span className="pulse-slash is-se" />
            </div>

            <span className="pulse-ring-dashed" />

            <div className="pulse-ring-inner">
              <span className="pulse-satellite" />
            </div>

            <span className="pulse-ring-dotted" />

            <div className="pulse-crosshair">
              <span />
              <span />
              <b />
            </div>

            <div className="pulse-arc">
              <div className="pulse-marker">
                <span className="pulse-ping" />
                <span className="pulse-marker-dot" />
              </div>
            </div>
          </div>

          <div className="pulse-hero-copy">
            <h1 className="pulse-title">CHRONOMARK</h1>

            <p className="pulse-tagline">
              Hours of lecture. One exact <em>moment.</em>
            </p>

            <p className="pulse-lede">
              The temporal intelligence engine that indexes 4-hour academic symposiums, audio
              phonemes, and chalkboard equations down to the exact millisecond.
            </p>

            <div className="pulse-actions">
              <a className="pulse-pill" href="#demo-lab">
                <span>Explore the demo</span>
                <i aria-hidden="true">β†—</i>
              </a>

              <button type="button" className="pulse-ghost">
                <span className="pulse-play" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="currentColor">
                    <path d="M5 3l14 9-14 9V3z" />
                  </svg>
                </span>
                <span>How it works</span>
                <span className="pulse-wave" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                  <i />
                </span>
              </button>
            </div>

            <div className="pulse-badges">
              <span>INDEXED REPOSITORIES:</span>
              {REPOSITORIES.map((repository) => (
                <span key={repository}>{repository}</span>
              ))}
            </div>
          </div>
        </section>

        <section className="pulse-section pulse-lab" id="demo-lab">
          <div className="pulse-wrap">
            <div className="pulse-section-head">
              <div>
                <p className="pulse-eyebrow">
                  <span>[03 // DEMO LAB]</span>
                  <span>β€”</span>
                  <span className="pulse-muted">Interactive Temporal Inspection</span>
                </p>
                <h2 className="pulse-h2">Multimodal Lecture Scanner</h2>
              </div>
              <p className="pulse-section-note">
                Query across voice phonemes, blackboard handwritten derivations, and synced slide
                transitions simultaneously.
              </p>
            </div>

            <div className="pulse-panel">
              <div className="pulse-hud">
                <div className="pulse-hud-left">
                  <span className="pulse-dots" aria-hidden="true">
                    <i className="is-rose" />
                    <i className="is-amber" />
                    <i className="is-emerald" />
                  </span>
                  <span className="pulse-faint pulse-hud-div">SESSION:</span>
                  <b>MIT_8.04_QUANTUM_PHYSICS_LEC19.mp4</b>
                </div>
                <div className="pulse-hud-right">
                  <span>
                    DURATION: <b>02:44:18</b>
                  </span>
                  <span className="pulse-hud-rate">
                    SAMPLE RATE: <b>48kHz / 60FPS</b>
                  </span>
                  <span className="pulse-chip">CHRONOMARK INDEXED</span>
                </div>
              </div>

              <div className="pulse-split">
                <div className="pulse-stage">
                  <div className="pulse-searchline">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                      <circle cx="11" cy="11" r="8" />
                      <line x1="21" y1="21" x2="16.65" y2="16.65" strokeLinecap="round" />
                    </svg>
                    <input
                      type="text"
                      readOnly
                      value="derivation of eigenvalues divergence matrix"
                      aria-label="Semantic query"
                    />
                    <b>3 MATCHES</b>
                  </div>

                  <div className="pulse-board">
                    <div className="pulse-chalk" aria-hidden="true">
                      <p className="pulse-chalk-cap">### SECTION 4.2: TENSOR EIGENVALUES ###</p>
                      <p className="pulse-chalk-eq">
                        ∇_θ L(θ) = 𝔼 [ (y - f(x; θ))ᵀ • Σ⁻¹ • ∂f/∂θ ]
                      </p>
                      <p className="pulse-chalk-warn">Ξ»_max (Aαµ€ A) &gt; Ξ³_critical β‡’ DIVERGENCE AT SCALE</p>
                      <p className="pulse-chalk-cap">
                        Proof continued: lim_{'{'}k→∞{'}'} ||W^{'{'}k+1{'}'} - W^k|| ≠ 0
                      </p>
                    </div>

                    <div className="pulse-board-top">
                      <span className="pulse-frame">
                        <i />
                        FRAME: 01:14:22.04
                      </span>
                      <span className="pulse-chip is-soft">CHALKBOARD OCR: 99.4%</span>
                    </div>

                    <div className="pulse-proof">
                      <div className="pulse-proof-head">
                        <b>EIGENVALUE PROOF BOX</b>
                        <span>CONF: 0.998</span>
                      </div>
                      <p>
                        "Notice how this matrix blows up when the step size violates Lipschitz
                        continuity."
                      </p>
                      <small>Voice: Prof. Strachan β€Ά Chalkboard sync: 0.04s</small>
                    </div>

                    <div className="pulse-board-foot">
                      <span className="pulse-time">
                        <i aria-hidden="true">❚❚</i>
                        <span>01:14:22</span>
                        <em>/ 02:44:18</em>
                      </span>
                      <span className="pulse-live">● 4K SYNCHRONIZED</span>
                    </div>
                  </div>

                  <div className="pulse-track-head">
                    <span>TEMPORAL PHONETIC DENSITY</span>
                    <b>PINPOINT MARK: 01:14:22</b>
                  </div>

                  <div className="pulse-scrub">
                    <div className="pulse-waveform" aria-hidden="true">
                      {WAVE.map((height, index) => (
                        <i
                          key={index}
                          className={
                            index % 10 === 5 || index % 10 === 6
                              ? 'is-emerald'
                              : index % 7 === 3
                                ? 'is-accent'
                                : undefined
                          }
                          style={{ height: `${height * 3}px` }}
                        />
                      ))}
                    </div>
                    <span className="pulse-playhead" aria-hidden="true">
                      <i />
                    </span>
                  </div>

                  <div className="pulse-legend">
                    <div>
                      <span>
                        <i className="is-accent" /> Formula Derivations
                      </span>
                      <span>
                        <i className="is-emerald" /> Core Definitions
                      </span>
                      <span>
                        <i className="is-amber" /> Exam Questions
                      </span>
                    </div>
                    <span>02:44:18 (100%)</span>
                  </div>
                </div>

                <aside className="pulse-results">
                  <div className="pulse-results-head">
                    <span>
                      <i className="pulse-dot" />
                      TEMPORAL INDEX HITS
                    </span>
                    <b>0.014s SEARCH TIME</b>
                  </div>

                  <div className="pulse-results-list">
                    {HITS.map((hit) => (
                      <article
                        key={hit.time}
                        className={`pulse-hit is-${hit.tone}${hit.active ? ' is-active' : ''}`}
                      >
                        <div className="pulse-hit-head">
                          <span className={`pulse-hit-time is-${hit.tone}`}>
                            {hit.time}
                            <em>{hit.tag}</em>
                          </span>
                          <span className="pulse-faint">{hit.match}</span>
                        </div>
                        <h4>{hit.title}</h4>
                        <p>{hit.quote}</p>
                        <div className="pulse-hit-foot">
                          <span>{hit.foot}</span>
                          <b>{hit.action}</b>
                        </div>
                      </article>
                    ))}
                  </div>

                  <div className="pulse-results-foot">
                    <span>TOTAL TOKENS: 41,200</span>
                    <span>SYNC DRIFT: &lt; 0.02s</span>
                    <span>EXPORT TO ANKI / OBSIDIAN β†—</span>
                  </div>
                </aside>
              </div>
            </div>
          </div>
        </section>

        <section className="pulse-section pulse-arch" id="how-it-works">
          <div className="pulse-wrap">
            <div className="pulse-center-head">
              <p className="pulse-eyebrow">[02 // TEMPORAL ARCHITECTURE]</p>
              <h2 className="pulse-h2 is-light">How sub-second temporal retrieval works.</h2>
              <p className="pulse-center-note">
                Conventional search requires full text transcripts and manual fast-forwarding.
                Chronomark binds auditory phonemes and visual telemetry directly to the video
                coordinate manifold.
              </p>
            </div>

            <div className="pulse-cards">
              {CARDS.map((card) => (
                <article key={card.number} className="pulse-card">
                  <span className="pulse-card-num">{card.number}</span>
                  <h3>{card.title}</h3>
                  <p>{card.body}</p>
                  <div className="pulse-card-foot">
                    <span>{card.left}</span>
                    <b>{card.right}</b>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="pulse-section pulse-bench" id="benchmarks">
          <div className="pulse-bench-wrap">
            <div className="pulse-bench-grid">
              <div>
                <p className="pulse-eyebrow">[04 // BENCHMARKS]</p>
                <h2 className="pulse-h2 is-light">The Speed Difference: 45 Minutes vs 1.4 Seconds.</h2>
                <p className="pulse-bench-note">
                  Students and researchers waste up to 30% of study time scrubbing backward and
                  forward through timeline sliders. Chronomark turns video archives into an instantly
                  accessible random-access memory array.
                </p>
                <div className="pulse-metrics">
                  <div>
                    <b>98.4%</b>
                    <span>Seek Time Eliminated</span>
                  </div>
                  <div>
                    <b>0.02s</b>
                    <span>Temporal Pinpoint Drift</span>
                  </div>
                </div>
              </div>

              <div className="pulse-meter">
                <div className="pulse-meter-row">
                  <div className="pulse-meter-head">
                    <span>
                      <i className="is-rose" />
                      TRADITIONAL VIDEO SCRUBBING
                    </span>
                    <b className="is-rose">~45 MINS WASTED / LECTURE</b>
                  </div>
                  <div className="pulse-track">
                    <span className="is-slow" style={{ width: '88%' }}>
                      Endless dragging, 2x speed scrubbing, missed chalkboard notes
                    </span>
                  </div>
                </div>

                <div className="pulse-meter-row">
                  <div className="pulse-meter-head">
                    <span>
                      <i className="is-accent" />
                      CHRONOMARK ORBITAL RETICLE
                    </span>
                    <b>1.4 SECONDS INSTANT JUMP</b>
                  </div>
                  <div className="pulse-track is-accent">
                    <span className="is-fast" style={{ width: '14%' }}>
                      1.4s
                    </span>
                    <em>Exact theorem timestamp pinpointed</em>
                  </div>
                </div>

                <div className="pulse-meter-foot">
                  <span>
                    INDEX SIZE: <b>4.2M+ Lecture Hours</b>
                  </span>
                  <span>
                    EMBEDDING: <b>Chrono-Vector 768-D</b>
                  </span>
                  <span className="pulse-emerald">● 100% AUDITABLE ACCURACY</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="pulse-section pulse-cta">
          <div className="pulse-cta-rings" aria-hidden="true">
            <span />
            <span />
          </div>

          <div className="pulse-cta-copy">
            <p className="pulse-eyebrow">[INSTANT EXTRACTION]</p>
            <h2 className="pulse-h2 is-light">
              Stop scrubbing through endless video. <br />
              <em>Start pinpointing.</em>
            </h2>
            <p className="pulse-cta-note">
              Paste any YouTube symposium, Panopto university link, or Zoom recording to index its
              temporal markers in seconds.
            </p>

            <div className="pulse-console">
              <form
                onSubmit={(event) => {
                  event.preventDefault()
                  window.location.assign('/upload')
                }}
              >
                <label className="pulse-console-field">
                  <span>URL:</span>
                  <input
                    type="text"
                    value={url}
                    onChange={(event) => setUrl(event.target.value)}
                    placeholder="https://youtube.com/watch?v=... or .mp4 link"
                    aria-label="Video URL"
                  />
                </label>
                <button type="submit">Chronomark Lecture β†—</button>
              </form>
            </div>

            <div className="pulse-cta-meta">
              <span>Free 10 Hours of Indexing</span>
              <span>β€Ά</span>
              <span>No Credit Card Required</span>
              <span>β€Ά</span>
              <span>Self-Hosted API Available</span>
            </div>
          </div>
        </section>
      </main>

      <footer className="pulse-footer">
        <div className="pulse-footer-grid">
          <div className="pulse-footer-brand">
            <span className="pulse-brand">
              <span className="pulse-mark is-small" aria-hidden="true">
                <i className="pulse-mark-dot" />
              </span>
              <span>CHRONOMARK</span>
            </span>
            <p>
              High-dimensional temporal indexing platform for academic lectures, technical keynotes,
              and deep tech video repositories.
            </p>
            <span className="pulse-footer-coords">
              COORDINATES: 42Β°21'35.9"N 71Β°05'32.1"W (CAMBRIDGE, MA)
            </span>
          </div>

          <div className="pulse-footer-col">
            <b>PLATFORM</b>
            <a href="#demo-lab">Lecture Scanner</a>
            <a href="#how-it-works">Chalkboard OCR</a>
            <a href="#how-it-works">Audio Phonemes</a>
            <a href="#demo-lab">Obsidian Plugin</a>
          </div>

          <div className="pulse-footer-col">
            <b>INTEGRATIONS</b>
            <a href="#demo-lab">Canvas LMS</a>
            <a href="#demo-lab">Panopto Vault</a>
            <a href="#demo-lab">YouTube Edu API</a>
            <a href="#demo-lab">Jupyter Notebooks</a>
          </div>

          <div className="pulse-telemetry">
            <div className="pulse-telemetry-head">
              <span>SYSTEM TELEMETRY</span>
              <span className="pulse-emerald">
                <i />
                ALL NODES NOMINAL
              </span>
            </div>
            <div>
              <span>UPTIME (365d):</span>
              <b>99.994%</b>
            </div>
            <div>
              <span>RETRIEVAL LATENCY:</span>
              <b>4.2ms avg</b>
            </div>
            <div>
              <span>ACTIVE EMBEDDINGS:</span>
              <b>1.48B vectors</b>
            </div>
          </div>
        </div>

        <div className="pulse-footer-base">
          <span>Β© 2025 Chronomark Technologies Inc. Precision Temporal Retrieval Systems.</span>
          <div>
            <a href="#top">PRIVACY POLICY</a>
            <a href="#top">TERMS OF TELEMETRY</a>
            <a href="#top">SECURITY (SOC-2)</a>
          </div>
        </div>
      </footer>
    </div>
  )
}

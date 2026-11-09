import { useEffect, useRef, useState } from 'react'
import './howItWorks.css'

/* "How it works".

   Its own composition, not the hero's: a numbered path down the left and a
   lecture player on the right whose waveform scans and then stops on the second
   the answer came from.

   The three steps are real buttons. Selecting one moves the player through its
   three states — idle, scanning, found — so the interaction is the explanation:
   choose a lecture, ask, watch the timeline stop.

   Motion is CSS only and finite: the scan line loops while it is asking, and the
   highlight, marker and answer are plain state-driven styles, so nothing can be
   left mid-flight. */

const STEPS = [
  {
    id: 'choose',
    n: '01',
    title: 'Choose your lecture',
    copy: 'Select a recorded lecture to explore.',
  },
  {
    id: 'ask',
    n: '02',
    title: 'Ask anything',
    copy: 'Ask a question about what was explained.',
  },
  {
    id: 'find',
    n: '03',
    title: 'Find the exact moment',
    copy: 'Get the answer and jump straight to the timestamp.',
  },
]

/* The waveform: one smooth envelope, drawn as a filled path plus a stroked edge. */
const WAVE =
  'M0 190 C40 186 62 150 96 148 C132 146 150 178 186 176 C214 174 232 150 262 152 ' +
  'C300 155 316 182 356 180 C392 178 404 150 440 146 C478 142 500 168 536 170 ' +
  'C566 172 584 158 612 150 C646 141 668 132 700 118'

const HIGHLIGHT = { start: 0.44, end: 0.53 }
const STAMP_PCT = 48
const STAMP = '01:04:12'

export default function HowItWorks() {
  const [active, setActive] = useState(0)
  const [inView, setInView] = useState(false)
  const rootRef = useRef(null)

  /* The section stays quiet until it is actually on screen, then its parts come
     up in order. Fires once: the section does not re-animate on every pass. */
  useEffect(() => {
    const el = rootRef.current
    if (!el) return undefined

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setInView(true)
      return undefined
    }

    /* The page scrolls inside #root, not the window, so the trigger reads the
       section's real position on every scroll frame instead of trusting an
       intersection ratio computed against the wrong root. */
    const scroller = document.getElementById('root')
    let done = false

    const reveal = () => {
      if (done) return
      done = true
      setInView(true)
      scroller?.removeEventListener('scroll', onScroll)
      window.removeEventListener('scroll', onScroll)
    }

    const check = () => {
      const rect = el.getBoundingClientRect()
      const vh = window.innerHeight || 800
      const visible = Math.min(rect.bottom, vh) - Math.max(rect.top, 0)
      // starts once roughly a twelfth of the section is on screen
      if (visible > Math.min(140, rect.height * 0.12)) reveal()
    }

    function onScroll() {
      check()
    }

    check()
    scroller?.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('scroll', onScroll, { passive: true })

    /* Nothing may be left invisible if something upstream swallows the events. */
    const guard = window.setTimeout(reveal, 6000)

    return () => {
      window.clearTimeout(guard)
      scroller?.removeEventListener('scroll', onScroll)
      window.removeEventListener('scroll', onScroll)
    }
  }, [])

  const scanning = active === 1
  const found = active === 2

  return (
    <section
      className={`hiw${inView ? ' is-inview' : ''}`}
      id="features"
      aria-label="How ChronoMark works"
      ref={rootRef}
    >
      <div className="hiw-grid" aria-hidden="true" />

      {/* Glow, kept well inside the section and faded at both ends so it can
          never be clipped on the boundary with the hero. */}
      <div className="hiw-blobs" aria-hidden="true">
        <span className="hiw-blob hiw-blob-a" />
        <span className="hiw-blob hiw-blob-b" />
        <span className="hiw-blob hiw-blob-c" />
      </div>

      <div className="hiw-content">

      <header className="hiw-head">
        <h2 className="hiw-title">How it works</h2>
        <p className="hiw-sub">
          From a question to the exact <em>moment.</em>
        </p>
      </header>

      <div className="hiw-body">
        <ol className="hiw-steps">
          <span className="hiw-rail" aria-hidden="true" />
          {STEPS.map((step, i) => (
            <li
              key={step.id}
              className={`hiw-step${i === active ? ' is-active' : ''}`}
              style={{ '--i': i }}
            >
              <span className="hiw-node" aria-hidden="true" />
              <button
                type="button"
                className="hiw-step-btn"
                aria-pressed={i === active}
                onClick={() => setActive(i)}
              >
                <span className="hiw-step-n">{step.n}</span>
                <span className="hiw-step-body">
                  <span className="hiw-step-title">{step.title}</span>
                  <span className="hiw-step-copy">{step.copy}</span>
                </span>
              </button>
            </li>
          ))}
        </ol>

        <div className={`hiw-player${scanning ? ' is-scanning' : ''}${found ? ' is-found' : ''}`}>
          <div className="hiw-player-bar">
            <span className="hiw-player-play" aria-hidden="true">
              <svg viewBox="0 0 12 14" fill="none">
                <path d="M1 1.4 11 7 1 12.6V1.4Z" fill="currentColor" />
              </svg>
            </span>
            <span className="hiw-player-name">Introduction to Machine Learning</span>
            <span className="hiw-player-tag">Lecture 01</span>
          </div>

          <div className="hiw-stage">
            <svg className="hiw-wave" viewBox="0 0 700 260" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <linearGradient id="hiwWave" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0" stopColor="#8B4DFF" stopOpacity="0.25" />
                  <stop offset="0.45" stopColor="#A855F7" stopOpacity="0.9" />
                  <stop offset="0.72" stopColor="#F42FA7" stopOpacity="1" />
                  <stop offset="1" stopColor="#F42FA7" stopOpacity="0.35" />
                </linearGradient>
                <linearGradient id="hiwFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="#A855F7" stopOpacity="0.34" />
                  <stop offset="1" stopColor="#A855F7" stopOpacity="0" />
                </linearGradient>
              </defs>

              <path className="hiw-wave-fill" d={`${WAVE} L700 260 L0 260 Z`} fill="url(#hiwFill)" />
              <path className="hiw-wave-line" d={WAVE} fill="none" stroke="url(#hiwWave)" strokeWidth="2.4" />

              {/* the found segment */}
              <rect
                className="hiw-wave-mark"
                x={`${HIGHLIGHT.start * 700}`}
                y="0"
                width={`${(HIGHLIGHT.end - HIGHLIGHT.start) * 700}`}
                height="260"
              />
            </svg>

            <span className="hiw-play" aria-hidden="true">
              <svg viewBox="0 0 14 16" fill="none">
                <path d="M1 1.6 13 8 1 14.4V1.6Z" fill="currentColor" />
              </svg>
            </span>

            <span className="hiw-scan" aria-hidden="true" />

            {found && (
              <div className="hiw-answer">
                <p className="hiw-answer-q">Why do models overfit?</p>
                <p className="hiw-answer-a">
                  It learns the noise in the training set instead of the pattern.
                </p>
                <span className="hiw-answer-t">{STAMP}</span>
              </div>
            )}
          </div>

          <div className="hiw-controls">
            <span className={`hiw-ctrl${scanning || found ? ' is-playing' : ''}`} aria-hidden="true">
              {scanning || found ? (
                <svg viewBox="0 0 12 12" fill="currentColor">
                  <rect x="1.5" y="1" width="3" height="10" rx="1" />
                  <rect x="7.5" y="1" width="3" height="10" rx="1" />
                </svg>
              ) : (
                <svg viewBox="0 0 12 12" fill="currentColor">
                  <path d="M2 1.4 10.5 6 2 10.6V1.4Z" />
                </svg>
              )}
            </span>

            <span className="hiw-time">00:00:00</span>

            <span className="hiw-track" aria-hidden="true">
              <span className="hiw-track-fill" style={{ width: found ? `${STAMP_PCT}%` : scanning ? '22%' : '0%' }} />
              <span className="hiw-track-mark" style={{ left: `${STAMP_PCT}%` }} />
            </span>

            <span className="hiw-time hiw-time-end">02:13:48</span>

            <span className="hiw-ctrl" aria-hidden="true">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
                <path d="M2 6h3l4-3v10L5 10H2V6Z" strokeLinejoin="round" />
                <path d="M12 5.5c1 1.4 1 3.6 0 5" strokeLinecap="round" />
              </svg>
            </span>

            <span className="hiw-ctrl" aria-hidden="true">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
                <path d="M2 6V2h4M14 10v4h-4M14 6V2h-4M2 10v4h4" strokeLinecap="round" />
              </svg>
            </span>
          </div>
        </div>
      </div>

      </div>
    </section>
  )
}

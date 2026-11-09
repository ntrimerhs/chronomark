import { useEffect, useRef, useState } from 'react'
import './aboutUs.css'

/* About us.

   Its own identity again: a vertical path of three ideas on the left, and on the
   right a convergence diagram — thin light trails from different heights meeting
   at one precise point, bracketed, with a beam carrying on to the right.

   Many hours of information, one exact moment. No dial, no player, no waveform.

   The trails are drawn with stroke-dashoffset when the section scrolls into view,
   then the target lights. Hovering or focusing an idea lights its own trail and
   the marker, so the diagram answers the list. */

const IDEAS = [
  {
    id: 'mission',
    label: 'Mission',
    copy: 'Make lecture knowledge instantly accessible.',
    d: 'M0 96 C 200 96 340 150 560 210',
  },
  {
    id: 'approach',
    label: 'Approach',
    copy: 'Combine AI-powered search with precise timestamp retrieval.',
    d: 'M0 210 C 220 210 350 210 560 210',
  },
  {
    id: 'vision',
    label: 'Vision',
    copy: 'No valuable explanation should get lost in hours of video.',
    d: 'M0 324 C 200 324 340 270 560 210',
  },
]

const POINT = { x: 560, y: 210 }

export default function AboutUs() {
  const [active, setActive] = useState(0)
  const [inView, setInView] = useState(false)
  const rootRef = useRef(null)

  useEffect(() => {
    const el = rootRef.current
    if (!el) return undefined

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setInView(true)
      return undefined
    }

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
      if (visible > Math.min(140, rect.height * 0.12)) reveal()
    }
    function onScroll() {
      check()
    }

    check()
    scroller?.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('scroll', onScroll, { passive: true })
    const guard = window.setTimeout(reveal, 6000)

    return () => {
      window.clearTimeout(guard)
      scroller?.removeEventListener('scroll', onScroll)
      window.removeEventListener('scroll', onScroll)
    }
  }, [])

  return (
    <section
      className={`au${inView ? ' is-inview' : ''}`}
      id="about"
      aria-label="About ChronoMark"
      ref={rootRef}
    >
      <div className="au-grid" aria-hidden="true" />
      <div className="au-blobs" aria-hidden="true">
        <span className="au-blob au-blob-a" />
        <span className="au-blob au-blob-b" />
      </div>
      <span className="au-cross au-cross-tl" aria-hidden="true" />
      <span className="au-cross au-cross-tr" aria-hidden="true" />
      <span className="au-cross au-cross-bl" aria-hidden="true" />
      <span className="au-cross au-cross-br" aria-hidden="true" />

      <div className="au-content">
        <header className="au-head">
          <p className="au-eyebrow">
            <span className="au-dash" aria-hidden="true" />
            03 / About
            <span className="au-dash" aria-hidden="true" />
          </p>
          <h2 className="au-title">About us</h2>
          <p className="au-sub">
            Why ChronoMark <em>exists.</em>
          </p>
        </header>

        <div className="au-body">
          <ol className="au-ideas">
            <span className="au-rail" aria-hidden="true" />
            {IDEAS.map((idea, i) => (
              <li
                key={idea.id}
                className={`au-idea${i === active ? ' is-active' : ''}`}
                style={{ '--i': i }}
              >
                <span className="au-node" aria-hidden="true" />
                <button
                  type="button"
                  className="au-idea-btn"
                  aria-pressed={i === active}
                  onMouseEnter={() => setActive(i)}
                  onFocus={() => setActive(i)}
                  onClick={() => setActive(i)}
                >
                  <span className="au-idea-title">{idea.label}</span>
                  <span className="au-idea-copy">{idea.copy}</span>
                </button>
              </li>
            ))}
          </ol>

          <div className="au-visual">
            <svg className="au-svg" viewBox="0 0 760 420" aria-hidden="true" focusable="false">
              <defs>
                <linearGradient id="auTrailPink" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0" stopColor="#F42FA7" stopOpacity="0" />
                  <stop offset="0.55" stopColor="#F42FA7" stopOpacity="0.85" />
                  <stop offset="1" stopColor="#FF6BC4" stopOpacity="1" />
                </linearGradient>
                <linearGradient id="auTrailViolet" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0" stopColor="#A855F7" stopOpacity="0" />
                  <stop offset="0.6" stopColor="#A855F7" stopOpacity="0.8" />
                  <stop offset="1" stopColor="#C98BFF" stopOpacity="1" />
                </linearGradient>
                <radialGradient id="auGlow" cx="0.5" cy="0.5" r="0.5">
                  <stop offset="0" stopColor="#F42FA7" stopOpacity="0.55" />
                  <stop offset="1" stopColor="#F42FA7" stopOpacity="0" />
                </radialGradient>
                <linearGradient id="auBeam" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0" stopColor="#F42FA7" stopOpacity="0.9" />
                  <stop offset="1" stopColor="#F42FA7" stopOpacity="0" />
                </linearGradient>
                <filter id="auSoft" x="-60%" y="-60%" width="220%" height="220%">
                  <feGaussianBlur stdDeviation="6" />
                </filter>
              </defs>

              <circle cx={POINT.x} cy={POINT.y} r="96" fill="url(#auGlow)" className="au-halo" />

              {IDEAS.map((idea, i) => (
                <g key={idea.id} className={`au-trail-group${i === active ? ' is-active' : ''}`}>
                  <path
                    className="au-trail-glow"
                    d={idea.d}
                    fill="none"
                    stroke={i === 0 ? '#F42FA7' : '#A855F7'}
                    filter="url(#auSoft)"
                  />
                  <path
                    className="au-trail"
                    d={idea.d}
                    style={{ '--delay': `${180 + i * 140}ms` }}
                  />
                </g>
              ))}

              {/* the beam that carries on to the edge */}
              <path className="au-beam" d={`M${POINT.x} ${POINT.y} L 760 ${POINT.y}`} />

              {/* the target */}
              <g className="au-target">
                <circle className="au-dot" cx={POINT.x} cy={POINT.y} r="7" fill="#F42FA7" />
                <circle className="au-dot-core" cx={POINT.x} cy={POINT.y} r="2.6" fill="#FFF0F8" />

                <g className="au-brackets">
                  <path d={`M${POINT.x - 34} ${POINT.y - 20} v -14 h 14`} />
                  <path d={`M${POINT.x + 34} ${POINT.y - 20} v -14 h -14`} />
                  <path d={`M${POINT.x - 34} ${POINT.y + 20} v 14 h 14`} />
                  <path d={`M${POINT.x + 34} ${POINT.y + 20} v 14 h -14`} />
                </g>
              </g>
            </svg>
          </div>
        </div>
      </div>
    </section>
  )
}

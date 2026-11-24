import { useEffect, useRef, useState } from 'react'
import CommandPalette from './CommandPalette'
import '../styles/landing-pulse.css'

/* The landing page, transcribed from the supplied markup.

   The seven drifting orbs, the spaced wordmark, the typewriter headline with its
   caret, the subhead, the floating pill navigation, and the two feature cards with
   their sample-query popovers.

   Two things are wired to this application: the cards open the real workspaces
   (/upload and /documents), and the round button at the end of the bar is our
   command palette rather than an account icon. The rest of the copy, sizes,
   timings and state behaviour are the reference's. */

const ORBS = [
  ['hv-orb-1', 'indigo'],
  ['hv-orb-2', 'cyan'],
  ['hv-orb-3', 'amber'],
  ['hv-orb-4', 'magenta'],
  ['hv-orb-5', 'emerald'],
  ['hv-orb-6', 'violet'],
  ['hv-orb-7', 'aqua'],
]

const PART_1 = 'Hours of lecture. '
const PART_2 = 'One exact moment.'

const NAV = [
  ['Platform', 'platform', true],
  ['Technology', 'technology', false],
  ['Research', 'research', false],
  ['Pricing', 'pricing', false],
]

const CARDS = [
  {
    id: 'video',
    href: '/upload',
    icon: 'smart_display',
    title: 'Video Analysis',
    subtitle: 'Audio phonemes & frames',
    badge: 'Confidence 99.4%',
    badgeIcon: 'timelapse',
    queries: [
      {
        text: '“When does the lecturer write the Schrödinger equation on the board?”',
        meta: '[01:42:15] • Chalkboard vision match',
        tone: 'primary',
      },
      {
        text: '“Jump to when speaker mentions backpropagation convergence rates”',
        meta: '[00:28:44] • Audio phoneme sync',
        tone: 'secondary',
      },
      {
        text: '“Find timestamps where students ask about gradient vanishing”',
        meta: '[02:11:09] • Multi-speaker voice tag',
        tone: 'primary',
      },
    ],
    footLeft: '60 fps Frame Index',
    footDot: 'primary',
    footRight: 'Temporal lock: ±0.04s',
  },
  {
    id: 'document',
    href: '/documents',
    icon: 'description',
    title: 'Document Analysis',
    subtitle: 'PDFs, slides & equations',
    badge: 'Multi-Doc OCR',
    badgeIcon: 'menu_book',
    queries: [
      {
        text: '“Extract theorem 3.2 proof and compare with slide 14 derivation”',
        meta: 'LaTeX AST • Cross-document link',
        tone: 'primary',
      },
      {
        text: '“Locate all formula instances for cross-entropy loss in chapters 4-6”',
        meta: 'Symbolic parsing • 14 occurrences',
        tone: 'secondary',
      },
      {
        text: '“Find where paper critiques transformer quadratic attention”',
        meta: 'Section 4.1 • Semantic contrast',
        tone: 'primary',
      },
    ],
    footLeft: 'MathPix + Vector Tree',
    footDot: 'cyan',
    footRight: 'Lossless AST',
  },
]

export default function PulseLanding() {
  const [typed, setTyped] = useState(0)
  const caretRef = useRef(null)

  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      setTyped(PART_1.length + PART_2.length)
      return undefined
    }

    let index = 0
    let deleting = false
    let timer = 0

    const step = () => {
      if (!deleting) {
        index += 1
        setTyped(index)
        if (index >= PART_1.length + PART_2.length) {
          deleting = true
          timer = window.setTimeout(step, 3800)
          return
        }
        const variance = Math.floor(Math.random() * 25) - 10
        timer = window.setTimeout(step, Math.max(25, 65 + variance))
      } else {
        index -= 1
        setTyped(index)
        if (index <= 0) {
          deleting = false
          timer = window.setTimeout(step, 600)
          return
        }
        timer = window.setTimeout(step, 35)
      }
    }

    timer = window.setTimeout(() => {
      setTyped(0)
      step()
    }, 400)

    return () => window.clearTimeout(timer)
  }, [])

  const part1 = PART_1.slice(0, Math.min(typed, PART_1.length))
  const part2 = typed > PART_1.length ? PART_2.slice(0, typed - PART_1.length) : ''

  return (
    <div className="lv">
      <div className="lv-orbits" aria-hidden="true">
        <div className="lv-flare" />
        {ORBS.map(([className, color]) => (
          <div key={className} className={`lv-orb ${className} is-${color}`} />
        ))}
        <div className="lv-veil" />
      </div>

      <header className="lv-header">
        <div className="lv-header-inner">
          <div className="lv-brand-wrap">
            <a className="lv-brand" href="#top">
              <span className="lv-brand-label">CHRONOMARK</span>
              <span className="lv-brand-ping">
                <span className="lv-brand-ping-wave" />
                <span className="lv-brand-ping-dot" />
              </span>
            </a>
          </div>

          <nav className="lv-nav" aria-label="Sections">
            {NAV.map(([label, path, current]) => (
              <a key={path} href={`#${path}`} className={current ? 'is-current' : undefined}>
                {label}
              </a>
            ))}
          </nav>

          <div className="lv-actions">
            <a className="lv-signin" href="#platform">
              Sign in
            </a>
            <a className="lv-start" href="/upload">
              <span>Get Started</span>
              <span className="material-symbols-outlined">arrow_forward</span>
            </a>
            <div className="lv-search-slot">
              <CommandPalette />
            </div>
          </div>
        </div>
      </header>

      <main className="lv-main" id="platform">
        <div className="lv-shell">
          <section className="lv-hero">
            <div className="lv-wordmark-wrap">
              <span className="lv-wordmark">CHRONOMARK</span>
            </div>

            <div className="lv-type-wrap">
              <h2 className="lv-type" aria-label={`${PART_1}${PART_2}`}>
                <span className="lv-type-1">{part1}</span>
                <span className="lv-type-2">{part2}</span>
                <span ref={caretRef} className="lv-caret" aria-hidden="true" />
              </h2>
            </div>

            <p className="lv-subhead">
              Search 4-hour academic symposiums, chalkboard equations, and audio phonemes with
              pinpoint temporal precision.
            </p>

            <div className="lv-cards">
              {CARDS.map((card) => (
                <div key={card.id} className="lv-card-holder">
                  <a className="lv-card" href={card.href}>
                    <div className="lv-card-left">
                      <div className="lv-card-icon">
                        <span className="material-symbols-outlined">{card.icon}</span>
                      </div>
                      <div className="lv-card-text">
                        <span className="lv-card-title">{card.title}</span>
                        <span className="lv-card-sub">{card.subtitle}</span>
                      </div>
                    </div>
                    <div className="lv-card-arrow">
                      <span className="material-symbols-outlined">arrow_forward</span>
                    </div>
                  </a>

                  <div className={`lv-popover is-${card.id}`}>
                    <div className="lv-popover-panel">
                      <div className="lv-popover-head">
                        <span className="lv-popover-title">
                          <span className="material-symbols-outlined">{card.badgeIcon}</span>
                          Sample Queries
                        </span>
                        <span className="lv-popover-badge">{card.badge}</span>
                      </div>

                      <div className="lv-popover-list">
                        {card.queries.map((query) => (
                          <div key={query.text} className="lv-popover-item">
                            <p>{query.text}</p>
                            <span className={`lv-popover-meta is-${query.tone}`}>{query.meta}</span>
                          </div>
                        ))}
                      </div>

                      <div className="lv-popover-foot">
                        <span className="lv-popover-foot-left">
                          <span className={`lv-foot-dot is-${card.footDot}`} />
                          {card.footLeft}
                        </span>
                        <span>{card.footRight}</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="lv-chips" />
          </section>
        </div>
      </main>
    </div>
  )
}

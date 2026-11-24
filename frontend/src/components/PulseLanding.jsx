import { useEffect, useRef, useState } from 'react'
import PulseHeader from './PulseHeader'
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
  },
  {
    id: 'document',
    href: '/documents',
    icon: 'description',
    title: 'Document Analysis',
    subtitle: 'PDFs, slides & equations',
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

      <PulseHeader reloadOnBrand />

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

                </div>
              ))}
            </div>

            <div className="lv-chips" />
          </section>

        <section className="lv-section" id="technology">
          <h2 className="lv-section-title">Technology</h2>
          <p className="lv-section-sub">
            Everything expensive happens in an API; this machine only orchestrates. The
            same stack the repository documents:
          </p>
          <div className="lv-stack">
            <div className="lv-stack-row">
              <span className="lv-stack-key">OCR</span>
              <span className="lv-stack-value">Google Document AI</span>
              <span className="lv-stack-note">page and paragraph structure, $1.50 / 1,000 pages</span>
            </div>
            <div className="lv-stack-row">
              <span className="lv-stack-key">SPEECH</span>
              <span className="lv-stack-value">Groq whisper-large-v3</span>
              <span className="lv-stack-note">every second cited, $0.04–0.11 / hour of audio</span>
            </div>
            <div className="lv-stack-row">
              <span className="lv-stack-key">EMBED</span>
              <span className="lv-stack-value">OpenAI text-embedding-3-small</span>
              <span className="lv-stack-note">1536 dimensions, $0.02 / 1M tokens</span>
            </div>
            <div className="lv-stack-row">
              <span className="lv-stack-key">ANSWER</span>
              <span className="lv-stack-value">DeepSeek deepseek-flash</span>
              <span className="lv-stack-note">grounded answers, streamed token by token</span>
            </div>
            <div className="lv-stack-row">
              <span className="lv-stack-key">INDEX</span>
              <span className="lv-stack-value">Qdrant</span>
              <span className="lv-stack-note">one collection per embedding width, old ones kept as backup</span>
            </div>
            <div className="lv-stack-row">
              <span className="lv-stack-key">MEDIA</span>
              <span className="lv-stack-value">Cloudflare R2 + Stream</span>
              <span className="lv-stack-note">audio extracted at the edge, nothing downloaded here</span>
            </div>
          </div>
          <p className="lv-section-note">
            Uploads are queued as files and executed by a fleet of workers, so the API answers
            in under a second while the reading and transcription happen behind it.
          </p>
        </section>

        <section className="lv-section" id="pricing">
          <h2 className="lv-section-title">Pricing</h2>
          <p className="lv-pending">Pending — coming soon.</p>
        </section>
        </div>
      </main>
    </div>
  )
}

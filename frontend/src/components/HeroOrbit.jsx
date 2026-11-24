import { useEffect, useRef, useState } from 'react'
import './heroOrbit.css'

/* The hero, transcribed from the supplied page.

   Seven drifting orbs behind a convergence flare, then the spaced wordmark with
   its violet text-shadow, the typewriter headline with its blinking caret, the
   subhead, and the command capsule with its hover, focus and ⌘K behaviour.

   The orbs are scoped to this section (the reference fixes them to the viewport,
   which would paint over the sections below it), everything else is the reference
   markup with the reference palette and timings. Submitting the capsule does not
   raise a toast; the button reads "Try now". */

const ORBS = [
  { className: 'hv-orb-1', color: 'indigo' },
  { className: 'hv-orb-2', color: 'cyan' },
  { className: 'hv-orb-3', color: 'amber' },
  { className: 'hv-orb-4', color: 'magenta' },
  { className: 'hv-orb-5', color: 'emerald' },
  { className: 'hv-orb-6', color: 'violet' },
  { className: 'hv-orb-7', color: 'aqua' },
]

const PART_1 = 'Hours of lecture. '
const PART_2 = 'One exact moment.'

export default function HeroOrbit() {
  const [typed, setTyped] = useState(0)
  const [query, setQuery] = useState('')
  const inputRef = useRef(null)

  /* typewriter: type, hold, delete, breathe, repeat */
  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      setTyped(PART_1.length + PART_2.length)
      return undefined
    }

    let charIndex = 0
    let deleting = false
    let timer = 0

    const step = () => {
      if (!deleting) {
        charIndex += 1
        setTyped(charIndex)
        if (charIndex >= PART_1.length + PART_2.length) {
          deleting = true
          timer = window.setTimeout(step, 3800)
          return
        }
        const variance = Math.floor(Math.random() * 25) - 10
        timer = window.setTimeout(step, Math.max(25, 65 + variance))
      } else {
        charIndex -= 1
        setTyped(charIndex)
        if (charIndex <= 0) {
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

  /* ⌘K / Ctrl+K focuses the field */
  useEffect(() => {
    const onKey = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const part1 = PART_1.slice(0, Math.min(typed, PART_1.length))
  const part2 = typed > PART_1.length ? PART_2.slice(0, typed - PART_1.length) : ''

  return (
    <div className="hv">
      <div className="hv-orbits" aria-hidden="true">
        <div className="hv-flare" />
        {ORBS.map((orb) => (
          <div key={orb.className} className={`hv-orb ${orb.className} is-${orb.color}`} />
        ))}
        <div className="hv-veil" />
      </div>

      <main className="hv-main">
        <section className="hv-hero">
          <div className="hv-wordmark-wrap">
            <span className="hv-wordmark">CHRONOMARK</span>
          </div>

          <div className="hv-type-wrap">
            <h2 className="hv-type" aria-label={`${PART_1}${PART_2}`}>
              <span className="hv-type-1">{part1}</span>
              <span className="hv-type-2">{part2}</span>
              <span className="hv-caret" aria-hidden="true" />
            </h2>
          </div>

          <p className="hv-subhead">
            Search 4-hour academic symposiums, chalkboard equations, and audio phonemes with pinpoint
            temporal precision.
          </p>

          <div className="hv-capsule-wrap">
            <form
              className="hv-capsule"
              onSubmit={(event) => {
                event.preventDefault()
                inputRef.current?.blur()
              }}
            >
              <div className="hv-capsule-icon">
                <span className="material-symbols-outlined">search</span>
              </div>

              <input
                ref={inputRef}
                className="hv-capsule-input"
                type="text"
                autoComplete="off"
                spellCheck="false"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder='Search across 10,000+ indexed lectures (e.g. "When did the professor derive backprop?")'
                aria-label="Search lectures"
              />

              <div className="hv-capsule-key">
                <span className="hv-capsule-key-symbol">⌘</span>K
              </div>

              <button className="hv-capsule-submit" type="submit">
                <span>Try now</span>
                <span className="material-symbols-outlined">timer</span>
              </button>
            </form>
          </div>

          <div className="hv-chips" />
        </section>
      </main>
    </div>
  )
}

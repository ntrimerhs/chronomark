import { useCallback, useEffect, useRef, useState } from 'react'
import './howItWorks.css'

/* "How it works" - the interactive three-step demo.

   Straight port of the supplied prototype: three tabs drive one lecture panel
   through its three states (source, question, moment). The state machine here is
   the prototype's, kept intact:

   - a step can be picked by hand, which stops the automatic run
   - REPLAY SEQUENCE runs 01 -> 02 -> 03 with the original pauses
   - the timestamp counts up to 01:24:37 while the timeline scans to it

   Only the shell changed: no second navigation, the section keeps this site's
   heading, and every style is scoped under .hiw-demo. */

const QUERY = 'Where is gradient descent explained?'
const LABELS = ['01 / LECTURE READY', '02 / QUERY SUBMITTED', '03 / MOMENT FOUND']
const STATUSES = ['SOURCE / READY', 'QUERY / SEARCHING', 'MATCH / FOUND']
const PROGRESS = [0, 29, 63]
const LECTURE_LENGTH = '02:13:48'
const TARGET_SECONDS = 1 * 3600 + 24 * 60 + 37
const TARGET_STAMP = '01:24:37'

const STEPS = [
  { title: 'Choose a lecture', copy: 'Start with the recording.' },
  { title: 'Ask anything', copy: 'Say what you want to know.' },
  { title: 'Find the moment', copy: 'Jump straight to the answer.' },
]

function formatTime(seconds) {
  const total = Math.round(seconds)
  return [
    Math.floor(total / 3600),
    Math.floor((total % 3600) / 60),
    total % 60,
  ]
    .map((part) => String(part).padStart(2, '0'))
    .join(':')
}

export default function HowItWorks() {
  const [reducedMotion] = useState(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  const [step, setStep] = useState(0)
  const [typed, setTyped] = useState('')
  const [answerShown, setAnswerShown] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [revealed, setRevealed] = useState(reducedMotion)

  const sectionRef = useRef(null)
  const timeRef = useRef(null)
  const footerTimeRef = useRef(null)
  const timersRef = useRef([])
  const frameRef = useRef(null)
  const stepRef = useRef(0)
  const pausedRef = useRef(false)
  const startedRef = useRef(false)

  const clearScheduled = useCallback(() => {
    timersRef.current.forEach((id) => window.clearTimeout(id))
    timersRef.current = []
    if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current)
    frameRef.current = null
  }, [])

  const schedule = useCallback((fn, ms) => {
    timersRef.current.push(window.setTimeout(fn, ms))
  }, [])

  const goToStep = useCallback(
    (next, manual = false) => {
      if (manual) pausedRef.current = true
      clearScheduled()
      stepRef.current = next
      setStep(next)
      setAnswerShown(false)
      setPreviewing(false)

      if (next === 0) {
        setTyped('')
        if (timeRef.current) timeRef.current.textContent = '00:00:00'
        if (footerTimeRef.current) {
          footerTimeRef.current.textContent = `00:00:00 / ${LECTURE_LENGTH}`
        }
        return
      }

      if (next === 1) {
        setTyped('')
        if (reducedMotion) {
          setTyped(QUERY)
          return
        }
        /* one character at a time, the prototype's cadence */
        for (let i = 1; i <= QUERY.length; i += 1) {
          schedule(() => {
            if (stepRef.current === 1) setTyped(QUERY.slice(0, i))
          }, 320 + i * 37)
        }
        return
      }

      /* next === 2 - count the clock up to the found moment */
      if (footerTimeRef.current) {
        footerTimeRef.current.textContent = `${formatTime(TARGET_SECONDS)} / ${LECTURE_LENGTH}`
      }
      setTyped(QUERY)

      if (reducedMotion) {
        if (timeRef.current) timeRef.current.textContent = formatTime(TARGET_SECONDS)
        setAnswerShown(true)
        return
      }

      if (timeRef.current) timeRef.current.textContent = '00:00:00'
      const duration = 1650
      /* the first frame is the clock's zero, so the count-up can never start
         behind itself and read backwards */
      let start = 0
      const tick = (now) => {
        if (stepRef.current !== 2) return
        if (!start) start = now
        const progress = Math.max(0, Math.min(1, (now - start) / duration))
        const eased = 1 - Math.pow(1 - progress, 3)
        if (timeRef.current) {
          timeRef.current.textContent = formatTime(TARGET_SECONDS * eased)
        }
        if (progress < 1) {
          frameRef.current = window.requestAnimationFrame(tick)
        } else {
          frameRef.current = null
          setAnswerShown(true)
        }
      }
      frameRef.current = window.requestAnimationFrame(tick)

      /* the count-up must land even if frames are throttled */
      schedule(() => {
        if (stepRef.current !== 2) return
        if (timeRef.current) timeRef.current.textContent = formatTime(TARGET_SECONDS)
        setAnswerShown(true)
      }, duration + 260)
    },
    [clearScheduled, reducedMotion, schedule],
  )

  const playSequence = useCallback(() => {
    pausedRef.current = false
    goToStep(0)
    if (reducedMotion) return
    schedule(() => {
      if (pausedRef.current) return
      goToStep(1)
      schedule(() => {
        if (!pausedRef.current) goToStep(2)
      }, 3000)
    }, 2200)
  }, [goToStep, reducedMotion, schedule])

  /* Reveal the section once it is genuinely on screen, then start the demo.
     The page scrolls inside #root, not the window. */
  useEffect(() => {
    const el = sectionRef.current
    if (!el) return undefined

    let done = false
    let sequence = false
    const scroller = document.getElementById('root')

    const check = () => {
      const rect = el.getBoundingClientRect()
      const viewport = window.innerHeight || 800
      const visible = Math.min(rect.bottom, viewport) - Math.max(rect.top, 0)
      if (!done && visible > Math.min(140, rect.height * 0.1)) {
        done = true
        setRevealed(true)
      }
      if (!sequence && visible > Math.min(420, rect.height * 0.45)) {
        sequence = true
        startedRef.current = true
        playSequence()
      }
      if (done && sequence) {
        scroller?.removeEventListener('scroll', onScroll)
        window.removeEventListener('scroll', onScroll)
      }
    }

    function onScroll() {
      check()
    }

    check()
    scroller?.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    window.addEventListener('hashchange', onScroll)
    const ticks = [80, 260, 700, 1400].map((ms) => window.setTimeout(check, ms))
    /* nothing may stay hidden if something upstream swallows the events */
    const guard = window.setTimeout(() => {
      setRevealed(true)
      if (!startedRef.current) playSequence()
    }, 6000)

    return () => {
      window.clearTimeout(guard)
      ticks.forEach(window.clearTimeout)
      window.removeEventListener('hashchange', onScroll)
      window.removeEventListener('resize', onScroll)
      scroller?.removeEventListener('scroll', onScroll)
      window.removeEventListener('scroll', onScroll)
    }
  }, [playSequence])

  /* A tab left in the background mid-sequence should not keep animating. */
  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) {
        pausedRef.current = true
        clearScheduled()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      clearScheduled()
    }
  }, [clearScheduled])

  const handleJump = () => {
    pausedRef.current = true
    clearScheduled()
    if (timeRef.current) timeRef.current.textContent = formatTime(TARGET_SECONDS)
    if (footerTimeRef.current) {
      footerTimeRef.current.textContent = `${TARGET_STAMP} / ${LECTURE_LENGTH}`
    }
    setAnswerShown(true)
    setPreviewing(true)
    schedule(() => setPreviewing(false), 2100)
  }

  const handleTabKey = (event, index) => {
    const keys = ['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Home', 'End']
    if (!keys.includes(event.key)) return
    event.preventDefault()
    let next = index
    if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = 2
    else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (index + 1) % 3
    else next = (index + 2) % 3
    document.getElementById(`step-tab-${next}`)?.focus()
    goToStep(next, true)
  }

  const revealClass = (name) => `${name}${revealed ? ' is-visible' : ''}`

  return (
    <div className="hiw-demo is-revealing">
      <section
        className="how-section"
        id="features"
        aria-labelledby="how-heading"
        ref={sectionRef}
      >
        <div className="section-inner">
          <div className={revealClass('section-title')} data-reveal>
            <h1 id="how-heading">
              How it works
              <span className="title-period">.</span>
            </h1>
            <p>
              From a question to the exact <em>moment.</em>
            </p>
          </div>

          <div
            className={revealClass('experience')}
            data-step={step}
            data-reveal
            id="experience"
          >
            <section className="steps" aria-label="How ChronoMark works">
              <div className="steps-heading">
                <span>THE PROCESS</span>
                <span>01—03</span>
              </div>

              <div
                className="step-rail"
                role="tablist"
                aria-orientation="vertical"
                aria-label="Explore each step"
              >
                {STEPS.map((item, i) => (
                  <button
                    key={item.title}
                    className={`step${i === step ? ' is-active' : ''}`}
                    type="button"
                    role="tab"
                    id={`step-tab-${i}`}
                    aria-controls={`scene-${i}`}
                    aria-selected={i === step}
                    tabIndex={i === step ? 0 : -1}
                    onClick={() => goToStep(i, true)}
                    onKeyDown={(event) => handleTabKey(event, i)}
                  >
                    <span className="step-index">{`0${i + 1}`}</span>
                    <span className="step-info">
                      <strong>{item.title}</strong>
                      <small>{item.copy}</small>
                    </span>
                    <span className="step-arrow" aria-hidden="true">
                      ↗
                    </span>
                  </button>
                ))}
              </div>

              <div className="step-bottom">
                <span className="current-step-label" aria-live="polite">
                  {LABELS[step]}
                </span>
                <button
                  id="replayButton"
                  className="replay-btn"
                  type="button"
                  aria-label="Replay the three-step demonstration"
                  onClick={playSequence}
                >
                  <span className="replay-icon" aria-hidden="true">
                    ↺
                  </span>{' '}
                  REPLAY SEQUENCE
                </button>
              </div>
            </section>

            <section className="showcase" aria-label="Interactive lecture demonstration">
              <div className="panel-header">
                <div className="panel-heading">
                  <span className="signal-dot" aria-hidden="true" />
                  <span>CHRONOMARK</span>
                </div>
                <div className="panel-status">
                  <span className="status-led" />
                  <span id="panelStatus">{STATUSES[step]}</span>
                </div>
              </div>

              <div className="scene-window">
                <div className="panel-guides" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                  <i />
                </div>

                <section
                  className={`scene scene-source${step === 0 ? ' is-current' : ''}`}
                  id="scene-0"
                  role="tabpanel"
                  aria-labelledby="step-tab-0"
                  hidden={step !== 0}
                >
                  <div className="source-visual">
                    <div className="source-topline">
                      LECTURE 001 <span>02:13:48</span>
                    </div>
                    <div className="source-main">
                      <div className="source-glyph" aria-hidden="true">
                        ▶
                      </div>
                      <div className="source-eyebrow">LOADED SOURCE</div>
                      <div className="source-title">
                        INTRODUCTION
                        <br />
                        TO MACHINE LEARNING
                      </div>
                      <div className="source-meta">
                        VIDEO / 128 MINUTES <span>•</span> TRANSCRIPT READY
                      </div>
                    </div>
                    <div className="source-bottomline">
                      PRESS STEP 02 TO ASK A QUESTION <span>↗</span>
                    </div>
                  </div>
                </section>

                <section
                  className={`scene scene-question${step === 1 ? ' is-current' : ''}`}
                  id="scene-1"
                  role="tabpanel"
                  aria-labelledby="step-tab-1"
                  hidden={step !== 1}
                >
                  <div className="question-screen">
                    <span className="mini-label">02 / ASK NATURALLY</span>
                    <h2>
                      Ask the lecture.
                      <br />
                      <em>Not the timeline.</em>
                    </h2>
                    <div className="query-line">
                      <span className="query-icon" aria-hidden="true">
                        ⌕
                      </span>
                      <span className="typed-query" id="typedQuery">
                        {typed}
                      </span>
                      <span className="caret" aria-hidden="true" />
                      <span className="query-enter" aria-hidden="true">
                        ↗
                      </span>
                    </div>
                    <div className="question-foot">
                      <span>SEARCHING 128 MINUTES OF CONTENT</span>
                      <span className="search-blips" aria-hidden="true">
                        <i />
                        <i />
                        <i />
                        <i />
                        <i />
                        <i />
                        <i />
                      </span>
                    </div>
                  </div>
                </section>

                <section
                  className={`scene scene-result${step === 2 ? ' is-current' : ''}`}
                  id="scene-2"
                  role="tabpanel"
                  aria-labelledby="step-tab-2"
                  hidden={step !== 2}
                >
                  <div className="result-screen">
                    <span className="mini-label">03 / EXACT MOMENT FOUND</span>
                    <div
                      className="time-title"
                      id="timeDisplay"
                      ref={timeRef}
                      aria-label="One hour twenty four minutes and thirty seven seconds"
                    >
                      00:00:00
                    </div>
                    <div className="result-subtitle">
                      THE ANSWER LIVES <em>HERE.</em>
                    </div>
                    <div className="signal-area" aria-hidden="true">
                      <svg
                        className="signal-svg"
                        viewBox="0 0 900 120"
                        preserveAspectRatio="none"
                      >
                        <defs>
                          <linearGradient id="hiwSignalGradient" x1="0" x2="1">
                            <stop offset="0" stopColor="#5944ae" />
                            <stop offset="0.57" stopColor="#b15ce7" />
                            <stop offset="0.8" stopColor="#F42FA7" />
                            <stop offset="1" stopColor="#A855F7" />
                          </linearGradient>
                        </defs>
                        <path
                          d="M 0 72 C 50 72 60 26 110 32 S 170 96 222 76 S 292 28 339 58 S 400 94 448 68 S 505 17 559 64 S 615 94 677 58 S 739 33 786 62 S 848 84 900 44"
                          fill="none"
                          stroke="url(#hiwSignalGradient)"
                          strokeWidth="2.8"
                        />
                      </svg>
                      <div className="scan-track">
                        <span className="scan-fill" />
                        <span className="scan-pin" />
                      </div>
                    </div>
                    <div className={`answer-reveal${answerShown ? ' is-shown' : ''}`}>
                      <div className="answer-check" aria-hidden="true">
                        ✓
                      </div>
                      <div>
                        <strong>Gradient descent, explained.</strong>
                        <span>Lecture 001 · Section 04</span>
                      </div>
                      <button
                        id="jumpButton"
                        className="jump-button"
                        type="button"
                        onClick={handleJump}
                      >
                        {previewing ? (
                          <>
                            {`PREVIEW AT ${TARGET_STAMP} `}
                            <span aria-hidden="true">✓</span>
                          </>
                        ) : (
                          <>
                            JUMP TO MOMENT <span aria-hidden="true">↗</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                </section>
              </div>

              <div className="panel-footer">
                <span className="player-title">
                  <span className="play-icon" aria-hidden="true">
                    ▶
                  </span>{' '}
                  INTRODUCTION TO MACHINE LEARNING
                </span>
                <div className="player-progress" aria-hidden="true">
                  <i style={{ width: `${PROGRESS[step]}%` }} />
                </div>
                <span className="play-time" id="footerTime" ref={footerTimeRef}>
                  00:00:00 / 02:13:48
                </span>
              </div>
            </section>
          </div>

          <div className={revealClass('below-experience')} data-reveal>
            <span>NOT JUST SEARCHABLE.</span>
            <span>
              FINDABLE TO THE SECOND. <b>↗</b>
            </span>
          </div>
        </div>
      </section>
    </div>
  )
}

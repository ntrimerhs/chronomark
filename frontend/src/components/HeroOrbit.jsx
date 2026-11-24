import './heroOrbit.css'

/* The hero, transcribed from the supplied section.

   Same structure, same copy, same measurements: the 1024px plate with its grid,
   the ambient glows, the four corner telemetry readouts, the 340 / 580 / 740px
   reticle with its rings, notches and satellite marker, and the foreground block
   pulled back over it with the wordmark, the tagline, the lede, the two actions
   and the repository line.

   Nothing else from earlier work is carried over; the classes are namespaced .hv-
   so the hero cannot inherit anything, and the section owns its whole plate. */

const MARKS = ['TIME', 'DATA', 'PRECISION', 'IMPACT']
const REPOSITORIES = ['MIT OPENCOURSEWARE', 'STANFORD CS ARCHIVES', 'NEURIPS 2024', 'CERN SYMPOSIUMS']

export default function HeroOrbit() {
  return (
    <section className="hv" data-purpose="orbital-radar-hero">
      <div className="hv-ambient" aria-hidden="true">
        <div className="hv-glow-core" />
        <div className="hv-glow-wide" />
      </div>

      <div className="hv-marks" aria-hidden="true">
        <div className="hv-marks-rule" />
        {MARKS.map((mark) => (
          <span key={mark}>{mark}</span>
        ))}
      </div>

      <div className="hv-stamp" aria-hidden="true">
        <span className="hv-stamp-rule" />
        <span className="hv-faint">T —</span>
        <span className="hv-pure hv-stamp-value">00:01:43</span>
      </div>

      <div className="hv-index" aria-hidden="true">
        <span className="hv-accent">01</span>
        <span className="hv-faint">/</span>
        <span className="hv-pure">∞</span>
        <span className="hv-index-rule" />
      </div>

      <div className="hv-latency" aria-hidden="true">
        <span className="hv-accent">///</span>
        <span className="hv-latency-text">SYSTEM ACTIVE • LATENCY 4.2ms</span>
      </div>

      <div className="hv-reticle" aria-hidden="true">
        <div className="hv-ring-outer">
          <div className="hv-notch hv-notch-n" />
          <div className="hv-notch hv-notch-s" />
          <div className="hv-notch hv-notch-e" />
          <div className="hv-notch hv-notch-w" />
          <div className="hv-slash hv-slash-nw" />
          <div className="hv-slash hv-slash-ne" />
          <div className="hv-slash hv-slash-sw" />
          <div className="hv-slash hv-slash-se" />
        </div>

        <div className="hv-ring-dashed" />

        <div className="hv-ring-inner">
          <div className="hv-satellite" />
        </div>

        <div className="hv-ring-dotted" />

        <div className="hv-crosshair">
          <div className="hv-crosshair-x" />
          <div className="hv-crosshair-y" />
          <div className="hv-crosshair-dot" />
        </div>

        <div className="hv-orbit">
          <div className="hv-orbit-arc">
            <div className="hv-marker">
              <div className="hv-marker-ping" />
              <div className="hv-marker-dot" />
            </div>
          </div>
        </div>
      </div>

      <div className="hv-content">
        <h1 className="hv-title" data-purpose="hero-title">
          CHRONOMARK
        </h1>

        <p className="hv-tagline" data-purpose="hero-tagline">
          Hours of lecture. One exact <span className="hv-tagline-em">moment.</span>
        </p>

        <p className="hv-lede">
          The temporal intelligence engine that indexes 4-hour academic symposiums, audio phonemes,
          and chalkboard equations down to the exact millisecond.
        </p>

        <div className="hv-actions" data-purpose="hero-actions">
          <a className="hv-pill" href="#demo-lab">
            <span className="hv-pill-label">Explore the demo</span>
            <span className="hv-pill-arrow">↗</span>
          </a>

          <button className="hv-ghost" type="button" data-purpose="listen-pinpoint-button">
            <div className="hv-play">
              <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M5 3l14 9-14 9V3z" />
              </svg>
            </div>
            <span>How it works</span>
            <div className="hv-wave" aria-hidden="true">
              <span className="hv-wave-1" />
              <span className="hv-wave-2" />
              <span className="hv-wave-3" />
              <span className="hv-wave-4" />
            </div>
          </button>
        </div>

        <div className="hv-badges">
          <span>INDEXED REPOSITORIES:</span>
          {REPOSITORIES.map((repository) => (
            <span key={repository}>{repository}</span>
          ))}
        </div>
      </div>
    </section>
  )
}

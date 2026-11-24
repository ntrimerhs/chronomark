import { Link } from 'react-router-dom'
import './heroOrbit.css'

/* The homepage hero, to the supplied composition, at the supplied measurements.

   Section 1024px tall with the 32px grid, the ambient core glow, the corner
   telemetry, the 340 / 580 / 740px reticle, and the foreground block pulled back
   over it by -260 / -420 / -490px so the wordmark sits on the dial rather than
   under it.

   Only the nine palette colours are used and the layout is expressed in the same
   pixel values as the reference; the reticle is decorative and takes no pointer
   events, and its motion stops under reduced motion. */

const MARKS = ['TIME', 'DATA', 'PRECISION', 'IMPACT']
const SOURCES = ['MIT OPENCOURSEWARE', 'STANFORD CS ARCHIVES', 'NEURIPS 2024', 'CERN SYMPOSIUMS']

export default function HeroOrbit() {
  return (
    <section className="hero2" id="top">
      <div className="hero2-ambient" aria-hidden="true">
        <span className="hero2-core" />
        <span className="hero2-wash" />
      </div>

      <div className="hero2-marks" aria-hidden="true">
        <span className="hero2-rule" />
        {MARKS.map((mark) => (
          <span key={mark}>{mark}</span>
        ))}
      </div>

      <div className="hero2-stamp" aria-hidden="true">
        <span className="hero2-rule-accent" />
        <span className="hero2-faint">T —</span>
        <b>00:01:43</b>
      </div>

      <div className="hero2-index" aria-hidden="true">
        <b>01</b>
        <span className="hero2-faint">/</span>
        <span className="hero2-ink">∞</span>
        <span className="hero2-rule-long" />
      </div>

      <div className="hero2-latency" aria-hidden="true">
        <b>///</b>
        <span>SYSTEM ACTIVE • LATENCY 4.2ms</span>
      </div>

      <div className="hero2-reticle" aria-hidden="true">
        <span className="hero2-ring-outer">
          <i className="hero2-notch is-n" />
          <i className="hero2-notch is-s" />
          <i className="hero2-notch is-e" />
          <i className="hero2-notch is-w" />
          <i className="hero2-slash is-nw" />
          <i className="hero2-slash is-ne" />
          <i className="hero2-slash is-sw" />
          <i className="hero2-slash is-se" />
        </span>

        <span className="hero2-ring-dashed" />

        <span className="hero2-ring-inner">
          <i className="hero2-satellite" />
        </span>

        <span className="hero2-ring-dotted" />

        <span className="hero2-crosshair">
          <i />
          <i />
          <b />
        </span>

        <span className="hero2-arc">
          <i className="hero2-marker">
            <b className="hero2-ping" />
            <b className="hero2-dot" />
          </i>
        </span>
      </div>

      <div className="hero2-copy">
        <h1 className="hero2-title">CHRONOMARK</h1>

        <p className="hero2-tagline">
          Hours of lecture. One exact <em>moment.</em>
        </p>

        <p className="hero2-lede">
          The temporal intelligence engine that indexes 4-hour academic symposiums, audio phonemes,
          and chalkboard equations down to the exact millisecond.
        </p>

        <div className="hero2-actions">
          <Link className="hero2-pill" to="/upload">
            <span>Explore the demo</span>
            <i aria-hidden="true">↗</i>
          </Link>

          <a className="hero2-ghost" href="#features">
            <span className="hero2-play" aria-hidden="true">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M5 3l14 9-14 9V3z" />
              </svg>
            </span>
            <span>How it works</span>
            <span className="hero2-wave" aria-hidden="true">
              <i />
              <i />
              <i />
              <i />
            </span>
          </a>
        </div>

        <div className="hero2-sources">
          <span>INDEXED REPOSITORIES:</span>
          {SOURCES.map((source) => (
            <span key={source}>{source}</span>
          ))}
        </div>
      </div>
    </section>
  )
}

import { Link } from 'react-router-dom'
import './heroOrbit.css'

/* The homepage hero, to the supplied section.

   Structure and measurements follow the reference element for element: a 90vh
   plate, two ambient glows, the 620px ticked ring with its 480px dashed orbit and
   340px dotted track, the axis lines and the corner cross, three telemetry
   readouts in the corners, then the wordmark, subtitle, intro, the two actions
   and the repository ticker.

   Colours stay inside the nine-colour palette (the reference's near-identical
   gradient stops and its emerald dot are expressed with the accent tones), and
   the reticle takes no pointer events. */

const MARKS = ['Time', 'Data', 'Precision', 'Impact']
const REPOSITORIES = ['MIT OPENCOURSEWARE', 'STANFORD CS ARCHIVES', 'NEURIPS 2024', 'CERN SYMPOSIUMS']

export default function HeroOrbit() {
  return (
    <section className="hero2">
      <div className="hero2-backdrop" aria-hidden="true">
        <span className="hero2-glow-wide" />
        <span className="hero2-glow-core" />

        <div className="hero2-dial">
          <div className="hero2-orbit-dashed">
            <div className="hero2-track-dotted" />
          </div>

          <span className="hero2-axis is-x" />
          <span className="hero2-axis is-y" />

          <span className="hero2-cross">+</span>

          <span className="hero2-orbit-dot">
            <i className="hero2-ping" />
            <i className="hero2-dot" />
          </span>
        </div>
      </div>

      <div className="hero2-marks" aria-hidden="true">
        {MARKS.map((mark) => (
          <span key={mark}>{mark}</span>
        ))}
      </div>

      <div className="hero2-index" aria-hidden="true">
        01 / ∞ —
      </div>

      <div className="hero2-stamp" aria-hidden="true">
        <span>—</span> T − 00:01:43
      </div>

      <div className="hero2-latency" aria-hidden="true">
        <i />
        <span>/// SYSTEM ACTIVE • LATENCY 4.2ms</span>
      </div>

      <div className="hero2-content">
        <h1 className="hero2-title">CHRONOMARK</h1>

        <p className="hero2-subtitle">
          Hours of lecture. One exact <em>moment.</em>
        </p>

        <p className="hero2-intro">
          The temporal intelligence engine that indexes 4-hour academic symposiums, audio phonemes,
          and chalkboard equations down to the exact millisecond.
        </p>

        <div className="hero2-actions">
          <Link className="hero2-primary" to="/upload">
            <span>Explore the demo</span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M7 17L17 7M17 7H7M17 7v10" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </Link>

          <a className="hero2-secondary" href="#features">
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M8 5v14l11-7z" />
            </svg>
            <span>How it works</span>
            <span className="hero2-wave" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
          </a>
        </div>

        <div className="hero2-ticker">
          <span className="hero2-ticker-label">INDEXED REPOSITORIES:</span>
          {REPOSITORIES.map((repository) => (
            <span key={repository}>{repository}</span>
          ))}
        </div>
      </div>
    </section>
  )
}

import { Link } from 'react-router-dom'
import './heroOrbit.css'

/* The homepage hero, to the supplied composition.

   A single centred monument: the reticle (calibrated rings, tick notches, a
   satellite dot and a pinging marker on the lower arc), the giant wordmark over
   it, the tagline whose last word carries the accent, the two actions, then the
   line of sources it works with.

   The reticle is decorative and takes no pointer events; the rings rotate on CSS
   only and stop under reduced motion. */

const LEFT_MARKS = ['Time', 'Data', 'Precision', 'Impact']

export default function HeroOrbit() {
  return (
    <section className="hero2" id="top">
      <div className="hero2-glow" aria-hidden="true" />
      <div className="hero2-wash" aria-hidden="true" />

      <div className="hero2-marks" aria-hidden="true">
        <span className="hero2-rule" />
        {LEFT_MARKS.map((mark) => (
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
        <span>∞</span>
        <span className="hero2-rule-long" />
      </div>

      <div className="hero2-latency" aria-hidden="true">
        <b>///</b>
        <span>System active · latency 4.2ms</span>
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
            <b />
            <b />
          </i>
        </span>
      </div>

      <div className="hero2-copy">
        <h1 className="hero2-title">Chronomark</h1>

        <p className="hero2-tagline">
          Hours of lecture. One exact <em>moment.</em>
        </p>

        <p className="hero2-lede">
          The temporal engine that indexes a four-hour symposium, its phonemes and its board notes
          down to the second, then hands you the moment you asked for.
        </p>

        <div className="hero2-actions">
          <Link className="hero2-pill" to="/upload">
            <span>Explore the demo</span>
            <i aria-hidden="true">↗</i>
          </Link>

          <a className="hero2-ghost" href="#features">
            <span className="hero2-play" aria-hidden="true">
              ▶
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
          <span>Works with:</span>
          <span>Lecture recordings</span>
          <span>Course slides</span>
          <span>Papers and notes</span>
          <span>Documents</span>
        </div>
      </div>
    </section>
  )
}

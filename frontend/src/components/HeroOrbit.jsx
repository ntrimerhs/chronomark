import { Link } from 'react-router-dom'
import './heroOrbit.css'

/* The homepage hero, built to the reference.

   One composition: a technical grid and three colour washes, a precision dial
   drawn in SVG, the CHRONOMARK wordmark sitting across it, the tagline and two
   controls, with small monospaced readouts at the edges.

   The dial is decorative and sits behind the type with pointer-events off. Its
   motion is CSS only — a marker travelling the inner orbit, a slower counter-
   rotating tick ring, a breathing glow — and it stops under reduced motion.

   Everything is real text and real SVG: nothing here is a screenshot, so the
   wordmark stays selectable and the circles stay crisp at any size. */

const WORD = 'CHRONOMARK'
const TICKS = Array.from({ length: 60 }, (_, i) => i * 6)
const CARDINALS = [0, 90, 180, 270]

export default function HeroOrbit() {
  return (
    <div className="hx">
      {/* the site's own mesh blobs, back on top of the plate */}
      <div className="hero-mesh" aria-hidden="true">
        <span className="mesh-blob mesh-blob-1" />
        <span className="mesh-blob mesh-blob-2" />
        <span className="mesh-blob mesh-blob-3" />
        <span className="mesh-blob mesh-blob-4" />
      </div>

      <div className="hx-wash hx-wash-pink" aria-hidden="true" />
      <div className="hx-wash hx-wash-violet" aria-hidden="true" />
      <div className="hx-wash hx-wash-blue" aria-hidden="true" />
      <div className="hx-grid" aria-hidden="true" />

      {/* edge readouts */}
      <div className="hx-edge hx-edge-tl" aria-hidden="true">
        <span className="hx-rule" />
        <p>
          TIME<br />DATA<br />PRECISION<br />IMPACT
        </p>
      </div>
      <p className="hx-edge hx-edge-tr" aria-hidden="true">
        <span>01 / ∞</span>
        <span className="hx-rule hx-rule-short" />
      </p>
      <p className="hx-edge hx-edge-bl" aria-hidden="true">
        <span className="hx-rule hx-rule-short" />
        <span>T — 00:00:00</span>
      </p>
      <p className="hx-edge hx-edge-br" aria-hidden="true">
        <span>///</span>
      </p>

      <div className="hx-stage">
        <svg className="hx-orbit" viewBox="0 0 700 700" aria-hidden="true" focusable="false">
          <defs>
            <linearGradient id="hxArc" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0" stopColor="#F42FA7" />
              <stop offset="1" stopColor="#A855F7" />
            </linearGradient>
            <linearGradient id="hxRing" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#A855F7" stopOpacity="0.5" />
              <stop offset="0.5" stopColor="#F42FA7" stopOpacity="0.16" />
              <stop offset="1" stopColor="#A855F7" stopOpacity="0.5" />
            </linearGradient>
            <filter id="hxGlow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="7" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* crosshairs */}
          <g className="hx-crosshair">
            <line x1="350" y1="0" x2="350" y2="700" />
            <line x1="0" y1="350" x2="700" y2="350" />
          </g>

          {/* outer + inner circles */}
          <circle className="hx-ring hx-ring-outer" cx="350" cy="350" r="322" />
          <circle className="hx-ring hx-ring-inner" cx="350" cy="350" r="233" />

          {/* dotted ring */}
          <circle className="hx-dotted" cx="350" cy="350" r="196" />

          {/* tick ring: rotates slowly, opposite to the marker */}
          <g className="hx-ticks">
            {TICKS.map((angle) => {
              const long = CARDINALS.includes(angle)
              return (
                <line
                  key={angle}
                  x1="350"
                  y1={long ? 18 : 26}
                  x2="350"
                  y2={long ? 44 : 38}
                  transform={`rotate(${angle} 350 350)`}
                  className={long ? 'hx-tick is-long' : 'hx-tick'}
                />
              )
            })}
          </g>

          {/* centre mark */}
          <g className="hx-centre">
            <line x1="336" y1="350" x2="364" y2="350" />
            <line x1="350" y1="336" x2="350" y2="364" />
          </g>

          {/* the travelling arc + marker */}
          <g className="hx-arc-group">
            <path className="hx-arc" d="M 470 145 A 233 233 0 0 1 560 300" />
            <path className="hx-arc-trail" d="M 402 128 A 233 233 0 0 1 470 145" />
            <g className="hx-marker">
              <circle cx="470" cy="145" r="20" fill="#F42FA7" opacity="0.16" />
              <circle cx="470" cy="145" r="9" fill="#F42FA7" filter="url(#hxGlow)" />
              <circle cx="470" cy="145" r="3.4" fill="#FFF0F8" />
            </g>
          </g>
        </svg>

        <h1 className="hx-word" aria-label="ChronoMark">
          {WORD.split('').map((char, i) => (
            <span key={`${char}-${i}`} style={{ '--i': i }}>
              {char}
            </span>
          ))}
        </h1>

        <p className="hx-tagline">
          Hours of lecture. One exact <em>moment.</em>
        </p>

        <div className="hx-actions">
          <Link className="hx-primary" to="/upload">
            Explore the demo
            <span className="hx-arrow" aria-hidden="true">
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                <path
                  d="M4 12 12 4M6 4h6v6"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          </Link>

          <a className="hx-ghost" href="#features">
            <span className="hx-play" aria-hidden="true">
              <svg width="8" height="9" viewBox="0 0 8 9" fill="none">
                <path d="M1 1.2 7 4.5 1 7.8V1.2Z" fill="currentColor" />
              </svg>
            </span>
            How it works
          </a>
        </div>
      </div>
    </div>
  )
}

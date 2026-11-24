import { Link } from 'react-router-dom'
import './heroOrbit.css'

/* The hero, to the Electric Pulse reference.

   Deep-blue radial plate, a precision dial drawn in SVG with two counter-rotating
   tick rings, a waveform that breathes, a glowing lime marker on the found moment
   and a floating "signal detected" card, with the copy on the left.

   Ticks and waveform bars are generated as arrays inside React rather than by
   scripting the DOM; all motion is CSS and stops under reduced motion. */

const TICKS = Array.from({ length: 96 }, (_, index) => index)
const BARS = Array.from({ length: 25 }, (_, index) => index)

function tickGeometry(index) {
  const y2 = index % 8 === 0 ? 77 : index % 4 === 0 ? 69 : 63
  const stroke = index % 16 === 0 ? '#C7F464' : index % 4 === 0 ? '#A2C7EB' : '#6399CB'
  return {
    y1: 54,
    y2,
    transform: `rotate(${index * 3.75} 300 300)`,
    stroke,
    strokeOpacity: index % 16 === 0 ? 1 : 0.72,
    strokeWidth: index % 8 === 0 ? 2 : 1,
  }
}

function barGeometry(index) {
  const height = 8 + Math.abs(Math.sin(index * 0.76) * Math.cos(index * 0.31)) * 52
  return {
    height,
    stroke: index > 14 ? '#7DD3FC' : '#3B82F6',
    opacity: 0.28 + 0.57 * (1 - index / 30),
  }
}

export default function HeroOrbit() {
  return (
    <div className="pulse-hero" id="top">
      <main className="pulse-hero-shell pulse-hero-grid">
        <section className="pulse-copy" aria-labelledby="heroTitle">
          <div className="pulse-eyebrow">
            <span className="pulse-line" />
            Precision, amplified
          </div>

          <h1 id="heroTitle">
            Every lecture.
            <br />
            <span className="pulse-outline">One exact</span>
            <br />
            <span className="pulse-lime">moment.</span>
          </h1>

          <p className="pulse-sub">
            Hours of information. One clear answer. Find the part that matters without searching
            through it all.
          </p>

          <div className="pulse-actions">
            <Link to="/upload" className="pulse-primary">
              Explore the demo <span aria-hidden="true">↗</span>
            </Link>
            <a href="#features" className="pulse-secondary">
              <span className="pulse-play" aria-hidden="true">
                ▶
              </span>
              How it works
            </a>
          </div>

          <div className="pulse-micro">
            <span>01 / find the signal</span>
            <span className="pulse-dot" />
            <span>Cut through the noise</span>
          </div>
        </section>

        <div className="pulse-visual">
          <div className="pulse-aura" aria-hidden="true" />
          <span className="pulse-corner">SIGNAL / 001</span>

          <svg
            className="pulse-dial"
            viewBox="0 0 600 600"
            role="img"
            aria-label="Illustrated circular timeline highlighting a moment at 24 minutes and 38 seconds"
          >
            <defs>
              <linearGradient id="pulseRing" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop stopColor="#3B82F6" />
                <stop offset="0.55" stopColor="#7DD3FC" />
                <stop offset="1" stopColor="#C7F464" />
              </linearGradient>
              <radialGradient id="pulseDisc">
                <stop stopColor="#0B408C" stopOpacity="0.6" />
                <stop offset="1" stopColor="#061226" stopOpacity="0.08" />
              </radialGradient>
              <filter id="pulseGlow" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="6" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            <circle cx="300" cy="300" r="259" fill="url(#pulseDisc)" />
            <circle cx="300" cy="300" r="246" fill="none" stroke="#3B82F6" strokeOpacity="0.43" strokeWidth="1.3" />
            <circle cx="300" cy="300" r="184" fill="none" stroke="#3B82F6" strokeOpacity="0.4" strokeWidth="1" />
            <circle
              cx="300"
              cy="300"
              r="142"
              fill="none"
              stroke="#7DD3FC"
              strokeOpacity="0.5"
              strokeWidth="1.5"
              strokeDasharray="1 10"
              strokeLinecap="round"
            />

            <g className="pulse-spin">
              {TICKS.map((index) => {
                const geometry = tickGeometry(index)
                return (
                  <line
                    key={index}
                    x1="300"
                    x2="300"
                    y1={geometry.y1}
                    y2={geometry.y2}
                    transform={geometry.transform}
                    stroke={geometry.stroke}
                    strokeOpacity={geometry.strokeOpacity}
                    strokeWidth={geometry.strokeWidth}
                  />
                )
              })}
            </g>

            <path
              d="M 300 54 A 246 246 0 0 1 543 264"
              stroke="url(#pulseRing)"
              strokeWidth="3"
              fill="none"
              strokeLinecap="round"
              filter="url(#pulseGlow)"
            />
            <path
              d="M 544 331 A 246 246 0 0 1 385 530"
              stroke="#3B82F6"
              strokeOpacity="0.65"
              strokeWidth="1.5"
              fill="none"
            />
            <g className="pulse-spin-reverse">
              <circle
                cx="300"
                cy="300"
                r="213"
                fill="none"
                stroke="#3B82F6"
                strokeOpacity="0.32"
                strokeWidth="1"
                strokeDasharray="3 23"
              />
            </g>

            <path d="M300 22V578M22 300H578" stroke="#7DD3FC" strokeOpacity="0.12" strokeDasharray="3 11" />

            <g>
              {BARS.map((index) => {
                const { height, stroke, opacity } = barGeometry(index)
                return [-1, 1].map((side) => {
                  const x = 300 + side * (108 + index * 4.5)
                  return (
                    <line
                      key={`${index}-${side}`}
                      x1={x}
                      x2={x}
                      y1={300 - height / 2}
                      y2={300 + height / 2}
                      stroke={stroke}
                      strokeOpacity={opacity}
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      className="pulse-wave"
                      style={{ animationDelay: `${index * -0.065}s` }}
                    />
                  )
                })
              })}
            </g>

            <circle cx="300" cy="300" r="92" fill="#061328" fillOpacity="0.83" stroke="#3B82F6" strokeOpacity="0.55" />
            <circle cx="300" cy="300" r="82" fill="none" stroke="#7DD3FC" strokeOpacity="0.28" />

            <text x="300" y="283" textAnchor="middle" fill="#9CBDD9" className="pulse-dial-label">
              MOMENT FOUND
            </text>
            <text x="300" y="328" textAnchor="middle" fill="#F8FAFC" className="pulse-dial-time">
              24:38
            </text>

            <circle className="pulse-point" cx="544" cy="331" r="19" fill="#C7F464" opacity="0.13" />
            <circle cx="544" cy="331" r="9" fill="#C7F464" filter="url(#pulseGlow)" />
            <circle cx="544" cy="331" r="3" fill="#F8FAFC" />

            <text x="300" y="43" textAnchor="middle" fill="#7DD3FC" className="pulse-dial-top">
              00 / 60
            </text>
          </svg>

          <div className="pulse-tooltip">
            <div className="pulse-tooltip-icon">⌁</div>
            <div>
              <strong>Signal detected</strong>
              <span>Jump to the exact moment ↗</span>
            </div>
          </div>
        </div>

        <div className="pulse-footerlabel">Chronomark / Locate what matters</div>
      </main>
    </div>
  )
}

import Header from './header.jsx'
import Footer from './Footer.jsx'
import ParticlesBackground from './ParticlesBackground.jsx';
import HeroOrbit from './HeroOrbit.jsx';
import HowItWorks from './HowItWorks.jsx';
import ChronoMarkLogo from '../icons/ChronoMarkLogo.jsx';
import '../styles/hero-split.css';
import { Fragment, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from "react-router-dom";

// The hero carries the supplied ChronoMark lockup instead of the old ASCII
// rendering of the previous name.

const ABOUT_QUESTIONS = [
  {
    q: 'who built this?',
    a: 'Christina - Ioanna Bezante and Enterisa Gjozi. Two students who got tired of scrubbing.',
    chips: [],
  },
  {
    q: 'what does it actually do?',
    a: 'Turns a recording into something you can question, and cites the second every answer was taken from.',
    chips: ['cites mm:ss'],
  },
  {
    q: 'does it run on my machine?',
    a: 'The transcript embeddings and the search index do. Audio goes to the OpenAI API to be transcribed, and the passages behind an answer travel with your question when you ask it.',
    chips: ['local: embeddings + index', 'remote: transcription + answers'],
  },
  {
    q: 'which languages?',
    a: 'Greek and English, including lectures that switch language mid-sentence.',
    chips: ['Ελληνικά', 'English'],
  },
  {
    q: 'what is it built with?',
    a: 'ffmpeg pulls the audio, Whisper transcribes it, sentence-transformers and CLIP embed it, Qdrant indexes it, FastAPI serves it.',
    chips: ['ffmpeg', 'Whisper', 'sentence-transformers', 'CLIP', 'Qdrant', 'FastAPI'],
  },
  {
    q: 'what is still missing?',
    a: 'Speaker labels, and more than one video indexed at a time. Uploading a new one currently clears the last.',
    chips: ['no speaker labels', 'one video at a time'],
  },
];

/* Chapter headings sit inside a liquid blob. The shape morphs on its own, and
   leans toward the pointer while a highlight tracks it. The blob is a pseudo
   element, so the heading stays plain, selectable text. */
/* One answer. Keyed on the question, so choosing another remounts it and the
   typewriter restarts without any setState-in-effect. */
function AboutAnswer({ item }) {
  const [typed, setTyped] = useState(0);
  const [answered, setAnswered] = useState(false);

  useEffect(() => {
    const timers = [];
    let typeId = 0;

    timers.push(window.setTimeout(() => {
      typeId = window.setInterval(() => {
        setTyped((n) => {
          if (n >= item.q.length) {
            window.clearInterval(typeId);
            return n;
          }
          return n + 1;
        });
      }, 34);
    }, 240));

    const typedAt = 240 + item.q.length * 34;
    timers.push(window.setTimeout(() => setAnswered(true), typedAt + 420));

    return () => {
      timers.forEach(window.clearTimeout);
      window.clearInterval(typeId);
    };
  }, [item]);

  return (
    <div className="prompt-card">
      <div className="prompt-bar">
        <span className="prompt-dot" />
        <span className="prompt-label">about — chronomark</span>
      </div>

      <div className="prompt-body">
        <div className="prompt-line">
          <span className="prompt-glyph">&gt;</span>
          <span className="prompt-query">
            {item.q.slice(0, typed)}
            <i className="prompt-cursor" />
          </span>
        </div>

        <div className={`prompt-reply${answered ? ' is-lit' : ''}`}>
          <p className="prompt-answer">{item.a}</p>
          {item.chips.length > 0 && (
            <div className="answer-chips">
              {item.chips.map((chip) => (
                <span key={chip} className="cue-tag">{chip}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* The section asks itself questions. Clicking a row answers it in the terminal;
   left alone it walks through them on its own, so the section is never still. */
function AboutPrompts() {
  const [active, setActive] = useState(0);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const id = window.setTimeout(() => {
      setActive((a) => (a + 1) % ABOUT_QUESTIONS.length);
    }, 7800);
    return () => window.clearTimeout(id);
  }, [active, nonce]);

  const pick = (i) => {
    setActive(i);
    setNonce((n) => n + 1); // restart the idle countdown on a manual pick
  };

  return (
    <div className="about-grid reveal reveal-delay-1">
      <ol className="about-questions">
        {ABOUT_QUESTIONS.map((item, i) => (
          <li key={item.q}>
            <button
              type="button"
              className={`about-question${i === active ? ' is-active' : ''}`}
              onClick={() => pick(i)}
            >
              <span className="about-question-mark">&gt;</span>
              <span className="about-question-text">{item.q}</span>
            </button>
          </li>
        ))}
      </ol>

      <div className="about-aside">
        <AboutAnswer key={active} item={ABOUT_QUESTIONS[active]} />
      </div>
    </div>
  );
}

/* Writes scrub progress straight to the DOM. Kept at module scope so the
   effects below need no dependencies beyond refs. */
function applyProgress(head, rail, value) {
  if (head) head.style.setProperty('--p', value.toFixed(4));
  if (rail) rail.setAttribute('aria-valuenow', String(Math.round(value * 100)));
}

/* A chapter heading is a subtitle track with a real scrubber.
 *
 * The title lights up word by word. It plays itself once as the section
 * arrives, so the words are never left unread — and the rail beneath it is
 * draggable: grab the playhead and the title scrubs under your hand, the way
 * you scrub a video. Arrow keys work too, and the rail is a proper slider for
 * assistive technology.
 *
 * Progress lives in a ref and goes straight to a CSS variable, so dragging
 * never re-renders React. */
function ChapterHead({ text, accentFrom = 0, lede, align = 'center', scrubber = true }) {
  const headRef = useRef(null);
  const railRef = useRef(null);
  const progress = useRef(0);
  const dragging = useRef(false);

  // Play once when the heading comes into view.
  useEffect(() => {
    const head = headRef.current;
    const rail = railRef.current;
    if (!head) return undefined;

    const set = (value) => {
      progress.current = Math.min(1, Math.max(0, value));
      applyProgress(head, rail, progress.current);
    };

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      set(1);
      return undefined;
    }

    let raf = 0;
    let startedAt = 0;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      const run = (now) => {
        if (!startedAt) startedAt = now;
        // A drag outranks the autoplay for as long as the pointer is down.
        if (!dragging.current) set((now - startedAt) / 1500);
        if (progress.current < 1) raf = window.requestAnimationFrame(run);
      };
      raf = window.requestAnimationFrame(run);
    }, { threshold: 0.5 });

    observer.observe(head);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(raf);
    };
  }, []);

  // Grab the playhead and scrub by hand.
  useEffect(() => {
    const rail = railRef.current;
    const head = headRef.current;
    if (!rail) return undefined;

    const set = (value) => {
      progress.current = Math.min(1, Math.max(0, value));
      applyProgress(head, rail, progress.current);
    };
    const positionOf = (event) => {
      const rect = rail.getBoundingClientRect();
      return rect.width ? (event.clientX - rect.left) / rect.width : 0;
    };

    const onDown = (event) => {
      dragging.current = true;
      // Capture keeps the drag alive outside the rail, but a synthetic or
      // already-released pointer throws — scrubbing should still work.
      try {
        rail.setPointerCapture(event.pointerId);
      } catch {
        /* not capturable; the move handler still tracks it */
      }
      set(positionOf(event));
    };
    const onMove = (event) => {
      if (dragging.current) set(positionOf(event));
    };
    const onUp = (event) => {
      dragging.current = false;
      try {
        if (rail.hasPointerCapture(event.pointerId)) rail.releasePointerCapture(event.pointerId);
      } catch {
        /* nothing captured; nothing to release */
      }
    };
    const onKey = (event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      dragging.current = true; // arrows override the autoplay too
      set(progress.current + (event.key === 'ArrowRight' ? 0.12 : -0.12));
    };

    rail.addEventListener('pointerdown', onDown);
    rail.addEventListener('pointermove', onMove);
    rail.addEventListener('pointerup', onUp);
    rail.addEventListener('pointercancel', onUp);
    rail.addEventListener('keydown', onKey);
    return () => {
      rail.removeEventListener('pointerdown', onDown);
      rail.removeEventListener('pointermove', onMove);
      rail.removeEventListener('pointerup', onUp);
      rail.removeEventListener('pointercancel', onUp);
      rail.removeEventListener('keydown', onKey);
    };
  }, []);

  return (
    <header
      ref={headRef}
      className={`chapter-head reveal${align === 'left' ? ' chapter-head-left' : ''}`}
    >
      <h2 className="chapter-title">
        <TitleWords text={text} accentFrom={accentFrom} />
      </h2>

      {scrubber ? (
        <div
          ref={railRef}
          className="chapter-scrub"
          role="slider"
          tabIndex={0}
          title="Drag to scrub the title"
          aria-label={`Scrub the heading: ${text}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={0}
        >
          <span className="chapter-scrub-line" />
          <span className="chapter-scrub-head" />
        </div>
      ) : null}

      <p className="chapter-lede">{lede}</p>
    </header>
  );
}

/* Chapter titles rise word by word out of a mask, then a gradient rule draws
   itself and the lede settles in behind it. All three are driven by
   .reveal-visible, which the page's existing IntersectionObserver already adds
   to anything carrying .reveal — so this needs no extra JavaScript. */
function TitleWords({ text, accentFrom = 0 }) {
  const words = text.split(' ');
  // Words light up in sequence across the first 82% of the scrub, so the last
  // one settles just before the rail finishes filling.
  const step = 0.82 / words.length;
  return words.map((word, i) => (
    <Fragment key={`${word}-${i}`}>
      {i > 0 ? ' ' : null}
      <span className="chapter-word">
        <span
          className={`chapter-word-inner${i >= accentFrom ? ' feature-heading-accent' : ''}`}
          style={{ '--i': i, '--step': step }}
        >
          {word}
        </span>
      </span>
    </Fragment>
  ));
}

function MainPage() {

  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    if (!location.hash) {
      return;
    }

    const targetId = location.hash.replace('#', '');
    const target = document.getElementById(targetId);
    if (!target) {
      return;
    }

    requestAnimationFrame(() => {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, [location.hash]);

  const heroWords = ['reveal', 'understand', 'unlock', 'transform'];
  const [wordIdx, setWordIdx] = useState(0);
  const [wordVisible, setWordVisible] = useState(true);

  useEffect(() => {
    const id = setInterval(() => {
      setWordVisible(false);
      setTimeout(() => {
        setWordIdx(i => (i + 1) % heroWords.length);
        setWordVisible(true);
      }, 380);
    }, 2600);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const els = document.querySelectorAll('.reveal');
    const obs = new IntersectionObserver(
      entries => entries.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('reveal-visible'); obs.unobserve(e.target); }
      }),
      { threshold: 0.14 }
    );
    els.forEach(el => obs.observe(el));
    return () => obs.disconnect();
  }, []);

  const heroRef = useRef(null);
  const labelRef = useRef(null);
  const trackRef = useRef(null);
  const scrubFillRef = useRef(null);
  const playheadRef = useRef(null);
  const typeRef = useRef(null);
  const cursorRef = useRef(null);
  const stepFillRef = useRef(null);
  const [tsReady, setTsReady] = useState(false);

  // Show a floating "Back to Top" button once scrolled past the hero.
  // #root is the real scroll container here (see the rAF effect below), so
  // we listen on it instead of window.
  const [showBackToTop, setShowBackToTop] = useState(false);

  useEffect(() => {
    const root = document.getElementById('root');
    const scrollEl = root || document.documentElement;
    const handleScroll = () => {
      const scrollTop = scrollEl.scrollTop || window.scrollY || 0;
      setShowBackToTop(scrollTop > 480);
    };
    scrollEl.addEventListener('scroll', handleScroll, { passive: true });
    return () => scrollEl.removeEventListener('scroll', handleScroll);
  }, []);

  const scrollToTop = () => {
    const root = document.getElementById('root');
    const scrollEl = root || document.documentElement;
    scrollEl.scrollTo({ top: 0, behavior: 'smooth' });
  };
  // rAF-based scroll progress — reads from the actual scroll container
  useEffect(() => {
    let rafId;
    const update = () => {
      const fill = stepFillRef.current;
      if (fill) {
        const trackH = fill.parentElement?.offsetHeight || 0;
        // #root has overflow-x:hidden which forces overflow-y:auto,
        // making it the real scroll container instead of window
        const root = document.getElementById('root');
        const scrollTop = (root && root.scrollTop)
          || document.body.scrollTop
          || document.documentElement.scrollTop
          || window.scrollY
          || 0;
        const scrollEl = (root && root.scrollTop) ? root
          : (document.body.scrollTop ? document.body : document.documentElement);
        const totalH = Math.max(
          scrollEl.scrollHeight - scrollEl.clientHeight,
          1
        );
        fill.style.height = `${Math.min(1, scrollTop / totalH) * trackH}px`;
      }

      rafId = requestAnimationFrame(update);
    };
    rafId = requestAnimationFrame(update);
    return () => cancelAnimationFrame(rafId);
  }, []);

  const typeText = 'ChronoMark transforms how you understand visual content. Discover patterns, extract meaning and unlock insights from video data like never before.';

  useEffect(() => {
    const el = typeRef.current;
    const cursor = cursorRef.current;
    if (!el || !cursor) return;
    el.textContent = '';
    let i = 0;
    let startTimer = setTimeout(() => {
      const tick = setInterval(() => {
        el.textContent = typeText.slice(0, ++i);
        if (i >= typeText.length) {
          clearInterval(tick);
          setTimeout(() => {
            if (cursor) cursor.classList.add('type-cursor-done');
          }, 1800);
        }
      }, 26);
      return () => clearInterval(tick);
    }, 700);
    return () => clearTimeout(startTimer);
  }, []);

  const totalSecs = 3600;

  const scrubTicks = [
    { label: '0:00',    pct: 0          },
    { label: '0:10:00', pct: 100 / 6    },
    { label: '0:20:00', pct: 200 / 6    },
    { label: '0:30:00', pct: 50         },
    { label: '0:40:00', pct: 400 / 6    },
    { label: '0:50:00', pct: 500 / 6    },
    { label: '1:00:00', pct: 100        },
  ];

  const handleHeroMouseMove = (e) => {
    const trackRect = trackRef.current?.getBoundingClientRect();
    if (!trackRect) return;
    const rawX = e.clientX - trackRect.left;
    const progress = Math.max(0, Math.min(1, rawX / trackRect.width));
    const pct = `${progress * 100}%`;
    if (scrubFillRef.current)  scrubFillRef.current.style.width = pct;
    if (playheadRef.current)   playheadRef.current.style.left  = pct;
    if (!tsReady) setTsReady(true);
    const secs = Math.floor(progress * totalSecs);
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60).toString().padStart(2, '0');
    const s = (secs % 60).toString().padStart(2, '0');
    if (labelRef.current) {
      labelRef.current.textContent = h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
    }
  };

  const navToUpload = (event) => {
    event.preventDefault()
    navigate("/upload")
  }

  return (
    <div className="page-content-wrap">
      <button
        type="button"
        className={`back-to-top${showBackToTop ? ' back-to-top-visible' : ''}`}
        onClick={scrollToTop}
        aria-label="Back to top"
      >
        <span className="back-to-top-label">Back to Top</span>
      </button>
      <div className="page-bar-track" aria-hidden="true">
        <div ref={stepFillRef} className="page-bar-fill" />
        <div className="page-stepper-node psn-1" />
        <div className="page-stepper-node psn-2" />
        <div className="page-stepper-node psn-3" />
      </div>
      <main className="main-hero" ref={heroRef} onMouseMove={handleHeroMouseMove}>
        {/* The hero carries its own backdrop (washes + grid) inside HeroOrbit. */}
        <HeroOrbit />
      </main>

      <HowItWorks />

    </div>
  )
}

export default MainPage

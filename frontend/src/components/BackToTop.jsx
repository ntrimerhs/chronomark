import { useEffect, useRef, useState } from 'react'
import '../styles/backToTop.css'

/* A quiet way back to the top of a long page.

   The app has two kinds of scroll surface: #root scrolls the marketing page and
   the video workspace, while the documents workspace scrolls its own panels.
   Scroll events do not bubble, but they do capture, so one listener on the
   document sees all of them; the element that moved is remembered so the button
   can send that same element back to its top instead of guessing. */

const SHOW_AFTER = 360

export default function BackToTop() {
  const [visible, setVisible] = useState(false)
  const scroller = useRef(null)

  useEffect(() => {
    const read = (event) => {
      const target = event?.target
      const element = target instanceof Element ? target : null

      // Ignore the horizontal rails and the chat composer's own 1px nudges.
      const moved = element
        ? Math.max(element.scrollTop || 0, element === document.documentElement ? window.scrollY : 0)
        : window.scrollY || 0

      const root = document.getElementById('root')
      const offset = Math.max(moved, window.scrollY || 0, root ? root.scrollTop : 0)
      const inside = element && element !== document.body && element !== document.documentElement
      if (inside && element.scrollTop > 0) scroller.current = element
      setVisible(offset > SHOW_AFTER)
    }

    read()
    document.addEventListener('scroll', read, { passive: true, capture: true })
    return () => document.removeEventListener('scroll', read, { capture: true })
  }, [])

  const toTop = () => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const behavior = reduce ? 'auto' : 'smooth'
    const target = scroller.current

    window.scrollTo({ top: 0, behavior })
    document.getElementById('root')?.scrollTo({ top: 0, behavior })
    if (target && target.isConnected) target.scrollTo({ top: 0, behavior })
    scroller.current = null
    setVisible(false)
  }

  return (
    <button
      type="button"
      className="btt"
      data-visible={visible ? 'true' : 'false'}
      onClick={toTop}
      aria-label="Back to top"
      tabIndex={visible ? 0 : -1}
    >
      <span className="btt-label">Back to top</span>
    </button>
  )
}

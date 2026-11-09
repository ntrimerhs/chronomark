/* The ChronoMark logo, used as delivered.

   These are the supplied artwork files, not a redraw: `chronomark-mark.png` is
   the clock-with-pin on its own (including its tick marks and grey hands),
   `chronomark-wordmark.png` is the wordmark split out of the same file so the
   header and footer can set it beside the mark, and `chronomark-lockup.png` is
   the full stacked lockup. Keeping the delivered pixels means the UI cannot
   drift from the brand file.

   Sizing is CSS only. An earlier version passed `style={{ height }}`, which beat
   the responsive `clamp()` in the stylesheet and pushed a 352px lockup into a
   350px mobile column. The width/height attributes below are just the intrinsic
   ratio, so the browser reserves the right box before the PNG loads. */

import lockup from '../icons/chronomark-lockup.png'
import mark from '../icons/chronomark-mark.png'
import wordmark from '../icons/chronomark-wordmark.png'

const SOURCES = { mark, wordmark, lockup }
const RATIOS = {
  mark: 478 / 479,
  wordmark: 1491 / 179,
  lockup: 1491 / 711,
}

export default function ChronoMarkLogo({
  variant = 'mark',
  height = 36,
  className = '',
  alt = 'ChronoMark',
  decorative = false,
}) {
  return (
    <img
      src={SOURCES[variant]}
      alt={decorative ? '' : alt}
      aria-hidden={decorative || undefined}
      className={className}
      width={Math.round(height * RATIOS[variant])}
      height={height}
      draggable="false"
    />
  )
}

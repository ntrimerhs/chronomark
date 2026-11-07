import { useEffect, useState } from 'react';
import { API_BASE_URL } from '../config';
import '../styles/framestrip.css';

const formatTime = (seconds) => {
  const total = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
};

/* A visual index of the video's keyframes: click any thumbnail to jump there.

   The frames come from the pass that now runs alongside transcription, and the
   manifest behind /video-frames is written by that same pass. An empty list is
   a normal state -- the video may not have been processed yet, or frame
   extraction may have failed -- so it renders nothing rather than an error. */
export default function FrameStrip({ videoId, onSeek, currentTime = 0 }) {
  const [frames, setFrames] = useState([]);

  useEffect(() => {
    if (!videoId) return undefined;

    let cancelled = false;

    fetch(`${API_BASE_URL}/video-frames/${videoId}`)
      .then((response) => (response.ok ? response.json() : { frames: [] }))
      .then((data) => {
        if (!cancelled) setFrames(Array.isArray(data.frames) ? data.frames : []);
      })
      .catch(() => {
        if (!cancelled) setFrames([]);
      });

    return () => {
      cancelled = true;
    };
  }, [videoId]);

  if (!videoId || frames.length === 0) return null;

  return (
    <div className="frame-strip">
      <div className="frame-strip-scroll">
        {frames.map((frame) => {
          const active = Math.abs(frame.t - currentTime) < 2;
          return (
            <button
              key={frame.url}
              type="button"
              className={`frame-strip-item${active ? ' is-active' : ''}`}
              onClick={() => onSeek(frame.t)}
              title={`Jump to ${formatTime(frame.t)}`}
            >
              <img src={`${API_BASE_URL}${frame.url}`} alt="" loading="lazy" />
              <span className="frame-strip-time">{formatTime(frame.t)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

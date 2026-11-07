import React from 'react';
import videojs from 'video.js';
import 'video.js/dist/video-js.css';
import '../styles/videojs.css';

//https://legacy.videojs.org/guides/react/

const SKIP_SECONDS = 10;

/** Jump forward, clamped so the player never seeks past the end. */
const skipForward = (player) => {
  if (!player || player.isDisposed()) return;

  const duration = player.duration();
  const target = player.currentTime() + SKIP_SECONDS;
  player.currentTime(
    Number.isFinite(duration) && duration > 0 ? Math.min(target, duration) : target,
  );
};

let skipButtonRegistered = false;

/** Adds the "+10s" control to the video.js control bar. */
const registerSkipButton = () => {
  if (skipButtonRegistered) return;
  skipButtonRegistered = true;

  const Button = videojs.getComponent('Button');

  class SkipForwardButton extends Button {
    createEl() {
      const element = videojs.dom.createEl('button', {
        className: 'vjs-skip-forward vjs-control vjs-button',
        title: `Skip forward ${SKIP_SECONDS} seconds (right-click the video does the same)`,
        'aria-label': `Skip forward ${SKIP_SECONDS} seconds`,
      });
      element.innerHTML = `<span class="vjs-skip-label">+${SKIP_SECONDS}s</span>`;
      return element;
    }
  }

  videojs.registerComponent('SkipForwardButton', SkipForwardButton);
};

export const VideoJSPlayer = (props) => {
  const videoRef = React.useRef(null);
  const playerRef = React.useRef(null);
  const { options, onReady } = props;

  const addLiveIndicator = (player) => {
    const progressBar = player.el()?.querySelector('.vjs-play-progress');
    if (!progressBar || progressBar.querySelector('.vjs-live-indicator')) {
      return;
    }

    const indicator = document.createElement('span');
    indicator.className = 'vjs-live-indicator';
    progressBar.appendChild(indicator);
  };

  /** The control-bar button, plus right-click anywhere on the video. */
  const addSkipControls = (player) => {
    registerSkipButton();

    const controlBar = player.controlBar;
    if (controlBar && !controlBar.getChild('SkipForwardButton')) {
      const button = controlBar.addChild('SkipForwardButton');
      if (button) {
        button.on('click', () => skipForward(player));
      }
    }

    // Right-click skips too, which is faster than aiming at the button.
    const surface = player.el();
    if (surface && !surface.dataset.skipBound) {
      surface.dataset.skipBound = 'true';
      surface.addEventListener('contextmenu', (event) => {
        event.preventDefault();
        skipForward(player);
      });
    }
  };

  React.useEffect(() => {
    // Make sure Video.js player is only initialized once
    if (!playerRef.current) {
      // The Video.js player needs to be _inside_ the component el for React 18 Strict Mode.
      const videoElement = document.createElement('video');

      videoElement.classList.add('video-js');
      videoElement.classList.add('vjs-big-play-centered');
      videoRef.current.appendChild(videoElement);

      const player = (playerRef.current = videojs(videoElement, options, () => {
        videojs.log('player is ready');
        addLiveIndicator(player);
        addSkipControls(player);
        onReady && onReady(player);
      }));

      // You could update an existing player in the `else` block here
      // on prop change, for example:
    } else {
      const player = playerRef.current;

      player.autoplay(options.autoplay);
      player.src(options.sources);
    }
  }, [options, videoRef]);

  // Dispose the Video.js player when the functional component unmounts
  React.useEffect(() => {
    const player = playerRef.current;

    return () => {
      if (player && !player.isDisposed()) {
        player.dispose();
        playerRef.current = null;
      }
    };
  }, [playerRef]);

  return (
    <div data-vjs-player>
      <div ref={videoRef} />
    </div>
  );
};

export default VideoJSPlayer;

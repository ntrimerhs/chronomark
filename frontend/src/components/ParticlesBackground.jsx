import { useMemo } from 'react';
import { Particles, ParticlesProvider } from '@tsparticles/react';
import { loadSlim } from '@tsparticles/slim';

// Must be a stable reference across renders (ParticlesProvider requirement).
const initEngine = async (engine) => {
  await loadSlim(engine);
};

export default function ParticlesBackground({ id = 'particles-js', interactive = false, flow = false }) {
  const options = useMemo(() => ({
    fullScreen: { enable: false },
    background: { color: { value: 'transparent' } },
    fpsLimit: 60,
    particles: {
      number: { value: 60, density: { enable: true, area: 900 } },
      color: { value: ['#A8A2FF', '#A8A2FF', '#F3F4F8'] },
      shape: { type: 'circle' },
      opacity: { value: { min: 0.15, max: 0.5 } },
      size: { value: { min: 1, max: 3 } },
      links: {
        enable: true,
        distance: 140,
        color: '#A8A2FF',
        opacity: 0.25,
        width: 1,
      },
      move: {
        enable: true,
        // flow: one direction, dead straight, slow — the field reads as
        // material passing a fixed point rather than drifting aimlessly.
        speed: flow ? 0.45 : 1.2,
        direction: flow ? 'right' : 'none',
        random: !flow,
        straight: flow,
        outModes: { default: 'out' },
      },
    },
    interactivity: {
      events: {
        onHover: { enable: true, mode: interactive ? 'bubble' : 'grab' },
        onClick: { enable: interactive, mode: 'push' },
        resize: { enable: true },
      },
      modes: {
        grab: { distance: 160, links: { opacity: 0.5 } },
        bubble: { distance: 180, size: 5, opacity: 1, color: { value: '#A8A2FF' }, duration: 0.4 },
        push: { quantity: 4 },
      },
    },
    detectRetina: true,
  }), [interactive, flow]);

  return (
    <ParticlesProvider init={initEngine}>
      <Particles id={id} className="particles-background" options={options} />
    </ParticlesProvider>
  );
}



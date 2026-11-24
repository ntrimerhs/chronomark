/* The palette the client gave. Every colour the site paints must come from it:
   #0B0B12 #141420 #1B1B2B #6F63D9 #A8A2FF #D8D6FF #F3F4F8 #A7ACBA #2A2C3B.

   Vendor stylesheets and the minifier both introduce colours that never existed
   in our source (video.js ships #73859f, lightningcss rewrites rgba() into 8 digit
   hex). Overriding selectors one by one leaves the originals in the bundle and
   anything forgotten keeps its old hue, so the palette is enforced twice:
   on vendor CSS as it is loaded, and on the finished bundle before it is written. */

const PALETTE = [
  [0x0b, 0x0b, 0x12], // bg
  [0x14, 0x14, 0x20], // surface
  [0x1b, 0x1b, 0x2b], // raised
  [0x6f, 0x63, 0xd9], // accent
  [0xa8, 0xa2, 0xff], // accent light
  [0xd8, 0xd6, 0xff], // accent pale
  [0xf3, 0xf4, 0xf8], // ink
  [0xa7, 0xac, 0xba], // muted
  [0x2a, 0x2c, 0x3b], // line
];

const HEX = /#([0-9a-fA-F]{3,8})\b/g;
const RGB = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(,\s*[\d.]+\s*)?\)/g;
const NAMED = /(?<=[:,\s])(white|black)(?![\w-])/g;

function role(r, g, b) {
  const max = Math.max(r, g, b) / 255;
  const min = Math.min(r, g, b) / 255;
  const light = (max + min) / 2;
  const delta = max - min;
  const sat = delta === 0 ? 0 : light > 0.5 ? delta / (2 - max - min) : delta / (max + min);

  if (light <= 0.1) return 0;
  if (light <= 0.16) return 1;
  if (light <= 0.23) return 2;
  if (light >= 0.86) return sat > 0.35 ? 5 : 6;
  if (sat < 0.18) {
    if (light < 0.32) return 2;
    if (light < 0.48) return 8;
    if (light < 0.76) return 7;
    return 6;
  }
  if (light < 0.55) return 3;
  if (light < 0.8) return 4;
  return 5;
}

function hexOf([r, g, b]) {
  return `#${[r, g, b].map((value) => value.toString(16).padStart(2, '0')).join('')}`;
}

function snapHex(r, g, b, alpha = '') {
  return hexOf(PALETTE[role(r, g, b)]) + alpha;
}

export function recolor(text) {
  return text
    .replace(HEX, (match, digits) => {
      let colour = digits;
      let alpha = '';

      if (colour.length === 3 || colour.length === 4) {
        const tail = colour.length === 4 ? colour.slice(3) : '';
        colour = colour
          .slice(0, 3)
          .split('')
          .map((char) => char + char)
          .join('');
        alpha = tail ? tail + tail : '';
      } else if (colour.length === 8) {
        alpha = colour.slice(6);
        colour = colour.slice(0, 6);
      } else if (colour.length !== 6) {
        return match;
      }

      const rgb = [0, 2, 4].map((index) => parseInt(colour.slice(index, index + 2), 16));
      return snapHex(...rgb, alpha);
    })
    .replace(RGB, (match, r, g, b, alpha) => {
      const [pr, pg, pb] = PALETTE[role(Number(r), Number(g), Number(b))];
      return alpha ? `rgba(${pr}, ${pg}, ${pb}${alpha})`.replace(/,\s*\)$/, ')') : `rgb(${pr}, ${pg}, ${pb})`;
    })
    .replace(NAMED, (match) => snapHex(...(match.toLowerCase() === 'white' ? [0xf3, 0xf4, 0xf8] : [0x0b, 0x0b, 0x12])));
}

export default function palettePlugin() {
  return {
    name: 'chronomark-palette',
    enforce: 'pre',

    transform(code, id) {
      if (!/node_modules[\\/](video\.js|katex|@videojs)/.test(id)) return null;
      if (!/\.css(\?|$)/.test(id)) return null;
      const recoloured = recolor(code);
      return recoloured === code ? null : { code: recoloured, map: null };
    },

    // Last word: the finished bundle. Catches whatever the minifier synthesised
    // and anything a dependency inlined into a JS chunk.
    generateBundle(_options, bundle) {
      for (const file of Object.values(bundle)) {
        if (file.type === 'asset' && file.fileName.endsWith('.css')) {
          const source = typeof file.source === 'string' ? file.source : file.source?.toString();
          if (source) file.source = recolor(source);
          continue;
        }
        if (file.type === 'chunk' && file.code) {
          file.code = recolor(file.code);
        }
      }
    },
  };
}

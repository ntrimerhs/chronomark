import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import palettePlugin from './vite.palette.js'

// https://vite.dev/config/
export default defineConfig({
  // Vendor CSS ships its own greys and blues; the palette plugin snaps them to
  // the nine colours the site uses, so no stray hue reaches the bundle.
  plugins: [palettePlugin(), react()],
})

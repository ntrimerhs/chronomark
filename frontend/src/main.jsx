import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './main.css'
import App from './App.jsx'
import './lib/authFetch.js'
// axios does not go through window.fetch; without this the upload pages ask
// the guarded API without a token and are told to sign in while signed in.
import './lib/authAxios.js'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

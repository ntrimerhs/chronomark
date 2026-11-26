import './App.css'
import PulseLanding from './components/PulseLanding.jsx'
import { BrowserRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import Form from './components/Form.jsx';
import PulseHeader from './components/PulseHeader.jsx';
import AuthPage from './components/AuthPage.jsx';
import AuthCallback from './components/AuthCallback.jsx';
import RequireAuth from './components/RequireAuth.jsx';
import ChatHome from './components/workspace/ChatHome.jsx';

/* /workspaces carries all three states of an analysis in one address: no
   parameter is the conversation that starts it, ?doc= is the document with its
   pages, ?video= is the recording with its player. Same sidebar, same chat, one
   entry point -- the old /upload and /documents pages are gone. */
function WorkspaceRoute() {
  // One page for every state of an analysis. A ?doc= or ?video= in the address
  // still opens that chat on arrival, but nothing here navigates: the shell
  // stays and only the pane beside the thread changes.
  return <ChatHome />;
}
import PrivacyPage from './components/PrivacyPage.jsx';
import TermsPage from './components/TermsPage.jsx';
import BackToTop from './components/BackToTop.jsx';
import { useLocation } from 'react-router-dom';
import useSmoothScroll from './hooks/useSmoothScroll.js';

/* The analysis scrolls inside its own panels, and a floating button sat over
   the composer of every chat. The marketing pages still get one. */
function BackToTopForRoute() {
  const { pathname } = useLocation();
  if (pathname.startsWith('/workspaces')) return null;
  return <BackToTop />;
}

function App() {
  useSmoothScroll();

  return (
    <Router>
      <BackToTopForRoute />
      <Routes>
        <Route path='/' element={<PulseLanding />}/>
        {/* Registration and sign-in are pages, not only the header dialog:
            Get Started has to land somewhere that can be linked to. */}
        {/* The workspace is where signing in lands: the sidebar frame and the one
            action a new account needs. */}
        <Route path='/workspaces' element={<RequireAuth><WorkspaceRoute /></RequireAuth>}/>
        {/* The old upload pages are gone. A bookmark to one of them still lands
            somewhere true instead of on an empty screen. */}
        <Route path='/upload' element={<Navigate to='/workspaces' replace />}/>
        <Route path='/documents' element={<Navigate to='/workspaces' replace />}/>
        <Route path='/privacy' element={<PrivacyPage />}/>
        <Route path='/terms' element={<TermsPage />}/>
        <Route path='/register' element={<AuthPage mode='signup' />}/>
        <Route path='/login' element={<AuthPage mode='signin' />}/>
        {/* Where Google and GitHub come back to: the session is already in
            localStorage by the time this renders, it only forwards to ?next. */}
        <Route path='/auth/callback' element={<AuthCallback />}/>
        {/* The analysis carries no footer: it ends in a conversation, and a
            footer under it only pushes the composer up. It is behind RequireAuth
            -- an account is what pays for the OCR, the transcription and the
            embeddings, so it is also what opens it. */}
      </Routes>
    </Router>
  )
}

export default App

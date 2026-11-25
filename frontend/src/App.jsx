import './App.css'
import PulseLanding from './components/PulseLanding.jsx'
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import Proxeiro from './components/Proxeiro.jsx'
import Documents from './components/Documents.jsx'
import Form from './components/Form.jsx';
import PulseHeader from './components/PulseHeader.jsx';
import AuthPage from './components/AuthPage.jsx';
import RequireAuth from './components/RequireAuth.jsx';
import useSmoothScroll from './hooks/useSmoothScroll.js';

function App() {
  useSmoothScroll();

  return (
    <Router>
      <Routes>
        <Route path='/' element={<PulseLanding />}/>
        {/* Registration and sign-in are pages, not only the header dialog:
            Get Started has to land somewhere that can be linked to. */}
        <Route path='/register' element={<AuthPage mode='signup' />}/>
        <Route path='/login' element={<AuthPage mode='signin' />}/>
        {/* The two chat workspaces carry no footer: video and documents both end
            in a conversation, and a footer under it only pushes the composer up.
            Both are behind RequireAuth -- an account is what pays for the OCR,
            the transcription and the embeddings, so it is also what opens them. */}
        <Route path='/upload' element={<RequireAuth><Form footer={false} header={false}><Proxeiro></Proxeiro></Form></RequireAuth>}/>
        <Route path='/documents' element={<RequireAuth><Form footer={false} header={false}><Documents></Documents></Form></RequireAuth>}/>
      </Routes>
    </Router>
  )
}

export default App

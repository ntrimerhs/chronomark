import './App.css'
import PulseLanding from './components/PulseLanding.jsx'
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import Proxeiro from './components/Proxeiro.jsx'
import Documents from './components/Documents.jsx'
import Form from './components/Form.jsx';
import PulseHeader from './components/PulseHeader.jsx';
import AuthPage from './components/AuthPage.jsx';
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
            in a conversation, and a footer under it only pushes the composer up. */}
        <Route path='/upload' element={<Form footer={false} header={false}><Proxeiro></Proxeiro></Form>}/>
        <Route path='/documents' element={<Form footer={false} header={false}><Documents></Documents></Form>}/>
      </Routes>
    </Router>
  )
}

export default App

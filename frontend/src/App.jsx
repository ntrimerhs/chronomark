import './App.css'
import PulseLanding from './components/PulseLanding.jsx'
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import Proxeiro from './components/Proxeiro.jsx'
import Documents from './components/Documents.jsx'
import Form from './components/Form.jsx';
import PulseHeader from './components/PulseHeader.jsx';
import useSmoothScroll from './hooks/useSmoothScroll.js';

function App() {
  useSmoothScroll();

  return (
    <Router>
      <Routes>
        <Route path='/' element={<PulseLanding />}/>
        {/* The two chat workspaces carry no footer: video and documents both end
            in a conversation, and a footer under it only pushes the composer up. */}
        <Route path='/upload' element={<Form footer={false} header={false}><PulseHeader inline /><Proxeiro></Proxeiro></Form>}/>
        <Route path='/documents' element={<Form footer={false} header={false}><PulseHeader inline /><Documents></Documents></Form>}/>
      </Routes>
    </Router>
  )
}

export default App

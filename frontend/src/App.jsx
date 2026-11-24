import './App.css'
import MainPage from './components/MainPage.jsx'
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import Proxeiro from './components/Proxeiro.jsx'
import Documents from './components/Documents.jsx'
import Form from './components/Form.jsx';
import useSmoothScroll from './hooks/useSmoothScroll.js';

function App() {
  useSmoothScroll();

  return (
    <Router>
      <Routes>
        <Route path='/' element={<Form><MainPage></MainPage></Form>}/>
        {/* The two chat workspaces carry no footer: video and documents both end
            in a conversation, and a footer under it only pushes the composer up. */}
        <Route path='/upload' element={<Form footer={false}><Proxeiro></Proxeiro></Form>}/>
        <Route path='/documents' element={<Form footer={false}><Documents></Documents></Form>}/>
      </Routes>
    </Router>
  )
}

export default App

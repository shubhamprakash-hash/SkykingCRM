import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Home from './pages/Home'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import TicketList from './pages/TicketList'
import TicketDetail from './pages/TicketDetail'
import Customers from './pages/Customers'

function RequireAuth({ children }) {
  const user = localStorage.getItem('skyking_user')
  return user ? children : <Navigate to="/login" />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<Login />} />
        <Route path="/dashboard" element={<RequireAuth><Dashboard /></RequireAuth>} />
        <Route path="/tickets/available" element={<RequireAuth><TicketList queue="available" /></RequireAuth>} />
        <Route path="/tickets/mine" element={<RequireAuth><TicketList queue="mine" /></RequireAuth>} />
        <Route path="/tickets/l1" element={<RequireAuth><TicketList queue="l1" /></RequireAuth>} />
        <Route path="/tickets/l2" element={<RequireAuth><TicketList queue="l2" /></RequireAuth>} />
        <Route path="/tickets/l3" element={<RequireAuth><TicketList queue="l3" /></RequireAuth>} />
        <Route path="/tickets/resolved" element={<RequireAuth><TicketList queue="resolved" /></RequireAuth>} />
        <Route path="/tickets/:id" element={<RequireAuth><TicketDetail /></RequireAuth>} />
        <Route path="/customers" element={<RequireAuth><Customers /></RequireAuth>} />
      </Routes>
    </BrowserRouter>
  )
}

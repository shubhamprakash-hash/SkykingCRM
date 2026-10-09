import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import { DEMO } from './api'
import App from './App'
import { AuthProvider } from './auth'
import './styles.css'

const Router = DEMO ? HashRouter : BrowserRouter

createRoot(document.getElementById('root')).render(
  <Router><AuthProvider><App /></AuthProvider></Router>
)

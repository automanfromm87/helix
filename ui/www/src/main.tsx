import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './assets/global.css'
import './assets/theme.css'
import './utils/toast'
import App from './App'
import { initializeAuth } from './api/auth'

initializeAuth()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

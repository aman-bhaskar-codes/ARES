import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { createRoot } from 'react-dom/client'
import App from './app/App'
import './styles.css'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 5000, refetchOnWindowFocus: false } } })
createRoot(document.getElementById('root')!).render(<StrictMode><BrowserRouter><QueryClientProvider client={queryClient}><App /></QueryClientProvider></BrowserRouter></StrictMode>)

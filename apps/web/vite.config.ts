import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000'
    }
  },
  build: {
    sourcemap: 'hidden',
    rolldownOptions: { output: { codeSplitting: { groups: [
      { name: 'react-vendor', test: /node_modules\/(?:react|react-dom|react-router|react-router-dom)\// },
      { name: 'markdown-vendor', test: /node_modules\/(?:react-markdown|remark-gfm)\// },
    ] } } },
  }
})

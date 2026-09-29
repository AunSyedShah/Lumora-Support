import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'


// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // In development the React app calls "/api/..." and Vite forwards it to Django,
    // so the browser sees one origin (no CORS needed while developing).
    // API_URL lets Django run on another port, e.g. API_URL=http://localhost:8001 bun run dev
    proxy: {
      '/api': process.env.API_URL || 'http://localhost:8000',
    },
  },
})

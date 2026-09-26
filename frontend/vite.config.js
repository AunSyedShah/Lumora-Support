import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'


// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // In development the React app calls "/api/..." and Vite forwards it to Django,
    // so the browser sees one origin (no CORS needed while developing).
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})

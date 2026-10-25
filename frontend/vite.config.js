import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import tailwindcss from '@tailwindcss/vite'


// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // API_URL can come from the environment or from frontend/.env.local (git-ignored).
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env }
  return {
    plugins: [react(), tailwindcss()],
    server: {
      // Inside Docker on Windows, file changes on the mounted folder are not announced: VITE_USE_POLLING=true checks for them.
      watch: env.VITE_USE_POLLING === 'true' ? { usePolling: true, interval: 300 } : undefined,
      // In development the React app calls "/api/..." and Vite forwards it to Django,
      // so the browser sees one origin (no CORS needed while developing).
      // API_URL lets Django run on another port, e.g. API_URL=http://127.0.0.1:8001 in frontend/.env.local
      proxy: {
        '/api': env.API_URL || 'http://localhost:8000',
      },
    },
  }
})

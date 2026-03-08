import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const frontendPort = Number(process.env.FRONTEND_PORT ?? 5173)

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: frontendPort,
    proxy: {
      '/api': 'http://localhost:8000',
      '/v1': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
})

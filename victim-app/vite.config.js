import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Port 5174 so it never clashes with the Swarm AI dashboard on 5173.
export default defineConfig({
  plugins: [react()],
  server: { port: 5174, strictPort: true },
  preview: { port: 5174, strictPort: true },
})

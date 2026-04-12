import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const host = process.env.TAURI_DEV_HOST

// https://vitejs.dev/config/
export default defineConfig({
  base: './',
  plugins: [react()],
  clearScreen: false,
  resolve: {
    dedupe: [
      'react',
      'react-dom',
      '@emotion/react',
      '@emotion/styled',
      '@mui/material',
      '@mui/system',
      '@mui/styled-engine',
    ],
  },
  optimizeDeps: {
    include: [
      '@emotion/react',
      '@emotion/styled',
      '@mui/material',
      '@mui/material/styles',
      '@mui/system',
      '@mui/styled-engine',
    ],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('@tauri-apps/api/')) {
            return 'tauri-api'
          }

          if (id.includes('node_modules/react-router') || id.includes('node_modules/@remix-run/')) {
            return 'router-vendor'
          }

          if (id.includes('node_modules/')) {
            return 'app-vendor'
          }
        },
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    host: host || false,
  },
  envPrefix: ['VITE_', 'TAURI_'],
})

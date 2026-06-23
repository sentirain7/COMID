import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,  // Allow fallback to next available port
    host: true,  // Listen on all addresses
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/graphql': {
        target: 'http://localhost:8000',
        ws: true,
        changeOrigin: true,
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return null

          if (
            id.includes('/react/') ||
            id.includes('/react-dom/') ||
            id.includes('/react-router-dom/')
          ) {
            return 'vendor-react'
          }

          if (id.includes('/node_modules/three/build/')) {
            return 'vendor-three-build'
          }

          if (id.includes('/node_modules/three/examples/')) {
            return 'vendor-three-examples'
          }

          if (id.includes('/troika-three-text/') || id.includes('/troika-three-utils/')) {
            return 'vendor-three-troika'
          }

          if (id.includes('/@react-spring/three/')) {
            return 'vendor-react-spring-three'
          }

          if (id.includes('/node_modules/three/')) {
            return 'vendor-three-core'
          }

          if (id.includes('/@react-three/')) {
            return 'vendor-react-three'
          }

          if (id.includes('/three-stdlib/')) {
            return 'vendor-three-stdlib'
          }

          if (id.includes('/recharts/')) {
            return 'vendor-charts'
          }

          if (id.includes('/@tanstack/react-query/')) {
            return 'vendor-query'
          }

          return null
        },
      },
    },
  }
})

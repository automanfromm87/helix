/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendUrl = env.BACKEND_URL || 'http://localhost:8000'

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5174,
      host: true,
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
          ws: true,
        },
      },
    },
    build: {
      sourcemap: true,
      // novnc uses top-level await; bump target so esbuild keeps it.
      target: 'es2022',
    },
    esbuild: {
      target: 'es2022',
      // Strip console.debug + debugger statements from production bundles —
      // we keep them in code for dev SSE tracing, but they shouldn't ship.
      // console.error / .warn stay so users still see real errors.
      pure: mode === 'production' ? ['console.debug'] : [],
      drop: mode === 'production' ? ['debugger'] : [],
    },
    optimizeDeps: {
      include: ['monaco-editor/esm/vs/editor/editor.api'],
      esbuildOptions: { target: 'es2022' },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.{test,spec}.{ts,tsx}'],
      coverage: {
        reporter: ['text', 'html'],
        include: ['src/lib/**', 'src/hooks/**', 'src/api/**'],
      },
    },
  }
})

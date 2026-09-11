import { defineConfig, loadEnv } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// The backend runs on :8000 in development. Everything under /api and /auth is
// proxied there so the HttpOnly session cookie stays first-party in the browser.
// Override with GRADER_BACKEND_URL in a .env.local if the backend lives elsewhere.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'GRADER_');
  const backend = env.GRADER_BACKEND_URL || 'http://localhost:8000';
  return {
    plugins: [svelte()],
    resolve: {
      alias: {
        $lib: new URL('./src/lib', import.meta.url).pathname,
      },
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': { target: backend, changeOrigin: false },
        '/auth': { target: backend, changeOrigin: false },
        '^/a/': { target: backend, changeOrigin: false },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      target: 'es2022',
    },
  };
});

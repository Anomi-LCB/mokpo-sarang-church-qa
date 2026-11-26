import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [tailwindcss()],
  esbuild: {
    jsx: 'automatic',
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:17865',
      '/downloads': 'http://127.0.0.1:17865',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});

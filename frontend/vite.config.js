import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";

/**
 * Vite config for the dashboard.
 *
 * The dev proxy exists so the browser never talks to a second origin:
 * same-origin means no CORS preflight and no CSRF exemption to reason
 * about in Phase 2.
 * @returns {object} Vite configuration
 */
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", changeOrigin: false },
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
});

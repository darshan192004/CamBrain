import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

/**
 * Vitest config for the dashboard unit tests (plan D7).
 *
 * Kept separate from vite.config.js so tests never pull the dev proxy or the
 * Tailwind plugin into the jsdom environment — the Vue plugin alone compiles
 * the SFCs under test.
 * @returns {object} Vitest configuration
 */
export default defineConfig({
  plugins: [vue()],
  test: {
    environment: "jsdom",
    include: ["src/__tests__/**/*.spec.js"],
  },
});

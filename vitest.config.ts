import path from "node:path";
import { defineConfig } from "vitest/config";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte({})],
  resolve: {
    alias: {
      "@": path.resolve("frontend"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["frontend/**/*.test.ts"],
  },
});

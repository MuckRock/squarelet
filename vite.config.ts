import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  base: "/static/",
  build: {
    manifest: "manifest.json",
    outDir: resolve("frontend/dist"),
    rollupOptions: {
      input: {
        main: resolve("frontend/main.ts"),
      },
    },
  },
});

import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  base: "/static/",
  build: {
    manifest: "manifest.json",
    rollupOptions: {
      input: {
        main: resolve("src/main.ts"),
      },
    },
  },
});

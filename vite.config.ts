import { globSync } from "fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// adapted from https://rollupjs.org/configuration-options/#input
// this creates an entrypoint for each .ts file in frontend/views
const views = Object.fromEntries(
  globSync("frontend/views/*.ts").map((file) => [
    // This removes `src/` as well as the file extension from each
    // file, so e.g. src/nested/foo.js becomes nested/foo
    path.relative(
      "frontend",
      file.slice(0, file.length - path.extname(file).length),
    ),
    // This expands the relative paths to absolute paths, so e.g.
    // frontend/views/foo.ts becomes /project/src/nested/foo.js
    fileURLToPath(new URL(file, import.meta.url)),
  ]),
);

console.log(views);

export default defineConfig({
  base: "/static/",
  build: {
    manifest: "manifest.json",
    outDir: path.resolve("frontend/dist"),
    rollupOptions: {
      input: {
        main: path.resolve("frontend/main.ts"),
        ...views,
      },
    },
  },
  plugins: [svelte({})],
  server: {
    port: 4200, // must be a port other than 5173
    host: true,
    cors: true,
    watch: {
      usePolling: true,
    },
  },
});

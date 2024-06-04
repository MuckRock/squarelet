const resolve = require("rollup-plugin-node-resolve");
const commonjs = require("rollup-plugin-commonjs");
const sourceMaps = require("rollup-plugin-sourcemaps");
import typescript from "rollup-plugin-typescript2";
import compiler from "@ampproject/rollup-plugin-closure-compiler";

const production = !process.env.ROLLUP_WATCH;

export default {
  input: `src/main.ts`,
  output: [
    { file: "../squarelet/static/js/main.js", format: "es", sourcemap: true },
  ],
  watch: {
    include: "src/**",
    clearScreen: false,
  },
  plugins: [
    resolve(),
    commonjs(),
    typescript({
      useTsconfigDeclarationDir: true,
      tsconfigOverride: {
        compilerOptions: {
          module: "ES2015",
          allowSyntheticDefaultImports: true,
        },
      },
      clean: production,
    }),
    !production && sourceMaps(),
    production && compiler(),
  ],
};

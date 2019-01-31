const resolve = require('rollup-plugin-node-resolve');
import typescript from 'rollup-plugin-typescript2';
import babel from 'rollup-plugin-babel';

export default {
  input: `src/index.ts`,
  output: [{file: 'src/main.js', format: 'es', sourcemap: true}],
  name: 'autocomplete',
  watch: {
    include: 'src/**',
  },
  plugins: [
    typescript({tsconfigOverride: {compilerOptions: {module: 'ES2015'}}}),
    resolve(),
    babel({
      exclude: 'node_modules/**',
    }),
  ],
};

/**
 * Flat config, using what `eslint-config-next` exports directly.
 *
 * Not through `FlatCompat`: the compat shim cannot serialise this config's
 * plugin graph and dies with a circular-structure error. The package already
 * ships flat arrays, so the shim buys nothing.
 */
import coreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default [
  { ignores: [".next/**", "out/**", "src/generated/**", "node_modules/**"] },
  ...coreWebVitals,
  ...nextTypescript,
  {
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
];

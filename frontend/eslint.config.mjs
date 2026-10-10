// eslint-config-next 16 already exports flat config arrays, so they are
// spread directly. The FlatCompat shim that older guides use crashes against
// it with "Converting circular structure to JSON".
import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const config = [
  ...coreWebVitals,
  ...typescript,
  { ignores: [".next/**", "node_modules/**", "legacy/**"] },
];

export default config;

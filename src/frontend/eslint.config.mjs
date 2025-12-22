import { defineConfig, globalIgnores } from "eslint/config";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";



const eslintConfig = defineConfig([
  ...nextCoreWebVitals,
  ...nextTypescript,
  globalIgnores(["out/**", "next-env.d.ts", ".next/**"]),
  { ignores: ["src/features/api/gen/**/*.ts"] },
  {
    rules: {
      "react-hooks/exhaustive-deps": "off",
      "react-hooks/refs": "off",
      "no-console": ["error", { allow: ["error", "warn"] }],
      "@typescript-eslint/no-unused-vars": "error",
      "react-hooks/set-state-in-effect": "warn",
    }
  }
]);

export default eslintConfig;

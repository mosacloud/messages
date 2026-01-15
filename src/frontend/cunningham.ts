import { defaultTokens } from "@gouvfr-lasuite/cunningham-react";
import { cunninghamConfig as tokens } from "@gouvfr-lasuite/ui-kit";

// Mosa brand color: #0443F2
const mergedColors = {
  ...defaultTokens.globals.colors,
  ...tokens.themes.default.globals.colors,
  "brand-500": "#0443F2",
  "brand-550": "#0443F2",
  "brand-600": "#033BD9",
  "brand-650": "#0334C0",
  "logo-1": "#0443F2",
};

tokens.themes.default.globals = {
  ...tokens.themes.default.globals,
  colors: mergedColors,
};

export default tokens;

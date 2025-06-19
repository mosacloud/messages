import { useState, useCallback } from "react";
import merge from "lodash/merge";

import { tokens } from "./cunningham-tokens";

type Tokens = typeof tokens.themes.default &
  Partial<(typeof tokens.themes)[keyof typeof tokens.themes]>;
type ColorsTokens = Tokens["theme"]["colors"];
type FontSizesTokens = Tokens["theme"]["font"]["sizes"];
type SpacingsTokens = Tokens["theme"]["spacings"];
type ComponentTokens = Tokens["components"];
export type Theme = keyof typeof tokens.themes;

interface ThemeStore {
  colorsTokens: Partial<ColorsTokens>;
  componentTokens: ComponentTokens;
  currentTokens: Partial<Tokens>;
  fontSizesTokens: Partial<FontSizesTokens>;
  setTheme: (theme: Theme) => void;
  spacingsTokens: Partial<SpacingsTokens>;
  theme: Theme;
  themeTokens: Partial<Tokens["theme"]>;
}

const getMergedTokens = (theme: Theme) => {
  return merge({}, tokens.themes["default"], tokens.themes[theme]);
};

const DEFAULT_THEME: Theme = "generic";
const defaultTokens = getMergedTokens(DEFAULT_THEME);

const initialState: Omit<ThemeStore, "setTheme"> = {
  colorsTokens: defaultTokens.theme.colors,
  componentTokens: defaultTokens.components,
  currentTokens: tokens.themes[DEFAULT_THEME] as Partial<Tokens>,
  fontSizesTokens: defaultTokens.theme.font.sizes,
  spacingsTokens: defaultTokens.theme.spacings,
  theme: DEFAULT_THEME,
  themeTokens: defaultTokens.theme,
};

export const useCunninghamTheme = (): ThemeStore => {
  const [themeState, setThemeState] =
    useState<Omit<ThemeStore, "setTheme">>(initialState);

  const setTheme = useCallback((theme: Theme) => {
    const newTokens = getMergedTokens(theme);

    setThemeState({
      colorsTokens: newTokens.theme.colors,
      componentTokens: newTokens.components,
      currentTokens: tokens.themes[theme] as Partial<Tokens>,
      fontSizesTokens: newTokens.theme.font.sizes,
      spacingsTokens: newTokens.theme.spacings,
      theme,
      themeTokens: newTokens.theme,
    });
  }, []);

  return {
    ...themeState,
    setTheme,
  };
};

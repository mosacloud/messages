import { APP_STORAGE_PREFIX } from "../config/constants";

const DEFAULT_LANGUAGES = [["en-US","English"],["fr-FR","Français"]];

// TODO: Tackle async loading of languages from backend
// to avoid declaring languages in multiple places (backend and frontend)
function getLanguagesFromEnv() {
  const languages = process.env.NEXT_PUBLIC_LANGUAGES;
  if (!languages) return DEFAULT_LANGUAGES;
  try {
      return JSON.parse(languages);
  } catch (error) {
    console.error("Error parsing languages from env", error);
    return DEFAULT_LANGUAGES;
  }
}

export const LANGUAGES = getLanguagesFromEnv();
export const LANGUAGES_ALLOWED = LANGUAGES.map((language: [string, string]) => language[0]);
export const LANGUAGE_LOCAL_STORAGE = APP_STORAGE_PREFIX + 'language';
export const BASE_LANGUAGE = process.env.NEXT_PUBLIC_DEFAULT_LANGUAGE || LANGUAGES_ALLOWED[0];

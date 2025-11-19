import path from 'path';

if (!process.env.FRONTEND_BASE_URL || !process.env.BACKEND_BASE_URL || !process.env.KEYCLOAK_BASE_URL) {
  throw new Error('FRONTEND_BASE_URL, BACKEND_BASE_URL and KEYCLOAK_BASE_URL must be set');
}

export const CLIENT_URL = process.env.FRONTEND_BASE_URL;
export const API_URL = process.env.BACKEND_BASE_URL;
export const AUTHENTICATION_URL = process.env.KEYCLOAK_BASE_URL;
export const STORAGE_STATE_PATH = path.join(__dirname, `./__tests__/.auth`);
export const FIXTURES_PATH = path.join(__dirname, `./fixtures`);

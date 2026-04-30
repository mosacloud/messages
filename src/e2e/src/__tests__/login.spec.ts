import { test, expect, Page, Route } from '@playwright/test';
import { signInKeycloakIfNeeded } from '../utils-test';

test.describe('Authentication with empty storage state', () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test('should authenticate', async ({ page, browserName }) => {
    const username = `user.e2e.${browserName}`;
    await signInKeycloakIfNeeded({ page, username });
  });
});

test.describe('Authentication with existing storage state', () => {
  test('should authenticate', async ({ page, browserName }) => {
    const username = `user.e2e.${browserName}`;
    await signInKeycloakIfNeeded({ page, username });
  });
});

const SILENT_LOGIN_RETRY_KEY = 'messages_silent-login-retry';

const mockConfigApi = async (page: Page, silentLoginEnabled: boolean) => {
  await page.route('**/api/v1.0/config/', async (route: Route) => {
    const response = await route.fetch();
    const json = await response.json();
    json.FRONTEND_SILENT_LOGIN_ENABLED = silentLoginEnabled;
    await route.fulfill({ response, json });
  });
};

const getSilentLoginRetryKey = async (page: Page): Promise<string | null> => {
  return page.evaluate(
    (key) => localStorage.getItem(key),
    SILENT_LOGIN_RETRY_KEY,
  );
};

const clearSilentLoginRetryKey = async (page: Page) => {
  await page.evaluate(
    (key) => localStorage.removeItem(key),
    SILENT_LOGIN_RETRY_KEY,
  );
};

// NOTE: Keycloak does not support silent login (prompt=none) when not running
// behind HTTPS, so we cannot fully test the silent re-authentication flow in
// this e2e environment. Instead, we verify that the correct requests are made
// (redirect to /authenticate/?silent=true) and that the app handles the
// outcome gracefully (showing the login page after a failed silent attempt).
test.describe('Silent Login', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('should attempt silent login with active Keycloak session', async ({
    page,
    browserName,
  }) => {
    const username = `user.e2e.${browserName}`;

    // Sign in normally to establish a Keycloak session
    await signInKeycloakIfNeeded({ page, username });

    // Clear app cookies but preserve Keycloak session cookies
    const cookies = await page.context().cookies();
    const keycloakCookies = cookies.filter((c) =>
      c.domain.includes('keycloak'),
    );
    await page.context().clearCookies();
    if (keycloakCookies.length > 0) {
      await page.context().addCookies(keycloakCookies);
    }

    // Clear localStorage retry key to allow silent login
    await clearSilentLoginRetryKey(page);

    // Enable silent login by intercepting the config endpoint
    await mockConfigApi(page, true);

    // Track the silent login redirect
    let silentLoginRequestMade = false;
    page.on('request', (request) => {
      const url = request.url();
      if (url.includes('/authenticate/') && url.includes('silent=true')) {
        silentLoginRequestMade = true;
      }
    });

    // Navigate to the app - the silent login redirect should occur
    await page.goto('/');

    // The login page is eventually shown because Keycloak returns a
    // "login_failed" error when not running behind HTTPS
    await expect(page.locator('button.pro-connect-button')).toBeVisible({
      timeout: 30000,
    });

    // Verify the silent login redirect occurred with the expected parameters
    expect(silentLoginRequestMade).toBe(true);
  });

  test('should fail gracefully without Keycloak session', async ({
    page,
    context,
  }) => {
    // Ensure no session exists
    await context.clearCookies();

    // Enable silent login
    await mockConfigApi(page, true);

    // Track the silent login redirect
    let silentLoginRequestMade = false;
    page.on('request', (request) => {
      const url = request.url();
      if (url.includes('/authenticate/') && url.includes('silent=true')) {
        silentLoginRequestMade = true;
      }
    });

    // Navigate to the app
    await page.goto('/');

    // Verify the ProConnect login button is shown (silent login failed,
    // retry key prevents re-attempt, login page displayed)
    await expect(page.locator('button.pro-connect-button')).toBeVisible({
      timeout: 30000,
    });

    // Verify the silent login redirect occurred
    expect(silentLoginRequestMade).toBe(true);

    // Verify localStorage has the retry key set (preventing immediate retry)
    const retryKeyValue = await getSilentLoginRetryKey(page);
    expect(retryKeyValue).not.toBeNull();
  });

  test('should show login page directly when silent login is disabled', async ({
    page,
    context,
  }) => {
    // Ensure no session exists
    await context.clearCookies();

    // Disable silent login
    await mockConfigApi(page, false);

    // Track to verify NO silent login redirect
    let silentLoginRequestMade = false;
    page.on('request', (request) => {
      const url = request.url();
      if (url.includes('/authenticate/') && url.includes('silent=true')) {
        silentLoginRequestMade = true;
      }
    });

    // Navigate to the app
    await page.goto('/');

    // Verify the ProConnect login button is shown directly (no silent login attempt)
    await expect(page.locator('button.pro-connect-button')).toBeVisible({
      timeout: 10000,
    });

    // Verify no silent login redirect was attempted
    expect(silentLoginRequestMade).toBe(false);

    // Verify no retry key in localStorage (silent login was never triggered)
    const retryKeyValue = await getSilentLoginRetryKey(page);
    expect(retryKeyValue).toBeNull();
  });
});


import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  exchangeOAuthCode: vi.fn(),
  getCurrentUser: vi.fn(),
  loginAccount: vi.fn(),
  logoutAccount: vi.fn(),
  registerAccount: vi.fn(),
}));

vi.mock("../services/api", () => api);

import { getAccessToken, getSessionVersion, saveAccessToken } from "../services/authSession";
import { useAuthStore } from "../stores/authStore";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

describe("auth session transitions", () => {
  afterEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    useAuthStore.setState({
      user: null,
      ready: false,
      busy: false,
      logoutInProgress: false,
      sessionVersion: getSessionVersion(),
      error: "",
    });
  });

  it("keeps the authenticated token only until the logout request completes", async () => {
    const logout = deferred<unknown>();
    api.logoutAccount.mockReturnValue(logout.promise);
    saveAccessToken("account-a-token");
    useAuthStore.setState({
      user: {
        id: "account-a",
        email: "a@example.com",
        name: "Account A",
        created_at: "2026-09-30T00:00:00Z",
      },
      ready: true,
      sessionVersion: getSessionVersion(),
    });

    const logoutPromise = useAuthStore.getState().logout();

    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().logoutInProgress).toBe(true);
    expect(getAccessToken()).toBe("account-a-token");

    logout.resolve(undefined);
    await logoutPromise;

    expect(getAccessToken()).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().logoutInProgress).toBe(false);
  });
});

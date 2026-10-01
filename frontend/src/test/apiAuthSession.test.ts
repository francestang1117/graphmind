import { afterEach, describe, expect, it, vi } from "vitest";

const axiosHarness = vi.hoisted(() => {
  const responseRejectors: Array<(error: unknown) => unknown> = [];
  const client = {
    interceptors: {
      request: { use: vi.fn() },
      response: {
        use: vi.fn((_fulfilled: unknown, rejected?: (error: unknown) => unknown) => {
          if (rejected) responseRejectors.push(rejected);
        }),
      },
    },
    post: vi.fn(),
  };
  const axiosDefault = {
    create: vi.fn(() => client),
    isAxiosError: vi.fn(() => true),
    post: vi.fn(),
  };
  return { axiosDefault, client, responseRejectors };
});

vi.mock("axios", () => ({ default: axiosHarness.axiosDefault }));

import { logoutAccount } from "../services/api";
import {
  beginLogout,
  clearTokens,
  finishLogout,
  getAccessToken,
  saveAccessToken,
} from "../services/authSession";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

describe("API authentication session boundaries", () => {
  afterEach(() => {
    clearTokens();
    finishLogout();
    vi.clearAllMocks();
  });

  it("does not save a refresh response that arrives after logout starts", async () => {
    const refresh = deferred<{ data: { access_token: string } }>();
    axiosHarness.axiosDefault.post.mockReturnValue(refresh.promise);
    saveAccessToken("account-a-token");

    const authRejected = axiosHarness.responseRejectors[1];
    expect(authRejected).toBeDefined();
    const request = authRejected({
      response: { status: 401 },
      config: { url: "/workspaces/", headers: {} },
    });
    await Promise.resolve();
    expect(axiosHarness.axiosDefault.post).toHaveBeenCalledWith(
      expect.stringContaining("/auth/refresh"),
      undefined,
      { withCredentials: true },
    );

    beginLogout();
    refresh.resolve({ data: { access_token: "late-account-a-token" } });

    await expect(request).rejects.toThrow("authentication session changed");
    expect(getAccessToken()).toBe("account-a-token");
  });

  it("uses the refresh cookie without serializing an empty logout body", async () => {
    axiosHarness.client.post.mockResolvedValue({ data: { message: "Logged out" } });

    await logoutAccount();

    expect(axiosHarness.client.post).toHaveBeenCalledWith(
      "/auth/logout",
      undefined,
      expect.objectContaining({
        _allowDuringLogout: true,
        _skipAuthRefresh: true,
      }),
    );
  });
});

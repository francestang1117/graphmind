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
  };
  const axiosDefault = {
    create: vi.fn(() => client),
    isAxiosError: vi.fn(() => true),
    post: vi.fn(),
  };
  return { axiosDefault, responseRejectors };
});

vi.mock("axios", () => ({ default: axiosHarness.axiosDefault }));

import "../services/api";
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

    beginLogout();
    refresh.resolve({ data: { access_token: "late-account-a-token" } });

    await expect(request).rejects.toThrow("authentication session changed");
    expect(getAccessToken()).toBe("account-a-token");
  });
});

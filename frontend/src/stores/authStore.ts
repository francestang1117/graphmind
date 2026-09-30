import axios from "axios";
import { create } from "zustand";
import type { User } from "../types";
import {
  getCurrentUser,
  exchangeOAuthCode,
  loginAccount,
  logoutAccount,
  registerAccount,
} from "../services/api";
import {
  beginLogout,
  beginSessionTransition,
  clearTokens,
  finishLogout,
  getSessionVersion,
  isLogoutInProgress,
  saveAccessToken,
} from "../services/authSession";

interface AuthState {
  user: User | null;
  ready: boolean;
  busy: boolean;
  logoutInProgress: boolean;
  sessionVersion: number;
  error: string;
  restore: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string) => Promise<void>;
  finishOAuth: (code: string) => Promise<void>;
  logout: () => Promise<void>;
  clearError: () => void;
}

function messageFor(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Could not complete that request. Check the backend and try again.";
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  ready: false,
  busy: false,
  logoutInProgress: false,
  sessionVersion: getSessionVersion(),
  error: "",

  restore: async () => {
    const requestVersion = getSessionVersion();
    try {
      const user = await getCurrentUser();
      if (requestVersion !== getSessionVersion() || isLogoutInProgress()) return;
      set({ user, ready: true, error: "" });
    } catch {
      if (requestVersion !== getSessionVersion() || isLogoutInProgress()) return;
      clearTokens();
      set({ user: null, ready: true });
    }
  },

  login: async (email, password) => {
    const requestVersion = beginSessionTransition();
    set({ busy: true, error: "", sessionVersion: requestVersion });
    try {
      const tokens = await loginAccount(email, password);
      if (requestVersion !== getSessionVersion()) return;
      saveAccessToken(tokens.access_token);
      const user = await getCurrentUser();
      if (requestVersion !== getSessionVersion()) return;
      set({ user, busy: false, sessionVersion: requestVersion });
    } catch (error) {
      if (requestVersion !== getSessionVersion()) return;
      clearTokens();
      set({ busy: false, error: messageFor(error) });
      throw error;
    }
  },

  register: async (email, password, name) => {
    const requestVersion = beginSessionTransition();
    set({ busy: true, error: "", sessionVersion: requestVersion });
    try {
      const tokens = await registerAccount(email, password, name);
      if (requestVersion !== getSessionVersion()) return;
      saveAccessToken(tokens.access_token);
      const user = await getCurrentUser();
      if (requestVersion !== getSessionVersion()) return;
      set({ user, busy: false, sessionVersion: requestVersion });
    } catch (error) {
      if (requestVersion !== getSessionVersion()) return;
      clearTokens();
      set({ busy: false, error: messageFor(error) });
      throw error;
    }
  },

  finishOAuth: async (code) => {
    const requestVersion = beginSessionTransition();
    set({ busy: true, error: "", sessionVersion: requestVersion });
    try {
      const tokens = await exchangeOAuthCode(code);
      if (requestVersion !== getSessionVersion()) return;
      saveAccessToken(tokens.access_token);
      const user = await getCurrentUser();
      if (requestVersion !== getSessionVersion()) return;
      set({ user, busy: false, sessionVersion: requestVersion });
    } catch (error) {
      if (requestVersion !== getSessionVersion()) return;
      clearTokens();
      set({ busy: false, error: messageFor(error) });
      throw error;
    }
  },

  logout: async () => {
    if (isLogoutInProgress()) return;
    const requestVersion = beginLogout();
    set({
      user: null,
      error: "",
      busy: false,
      logoutInProgress: true,
      sessionVersion: requestVersion,
    });
    try {
      await logoutAccount();
    } finally {
      clearTokens();
      finishLogout();
      set({
        user: null,
        busy: false,
        logoutInProgress: false,
        sessionVersion: getSessionVersion(),
      });
    }
  },

  clearError: () => set({ error: "" }),
}));

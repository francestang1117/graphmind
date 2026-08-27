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
  clearTokens,
  saveAccessToken,
} from "../services/authSession";

interface AuthState {
  user: User | null;
  ready: boolean;
  busy: boolean;
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
  error: "",

  restore: async () => {
    try {
      const user = await getCurrentUser();
      set({ user, ready: true, error: "" });
    } catch {
      clearTokens();
      set({ user: null, ready: true });
    }
  },

  login: async (email, password) => {
    set({ busy: true, error: "" });
    try {
      const tokens = await loginAccount(email, password);
      saveAccessToken(tokens.access_token);
      const user = await getCurrentUser();
      set({ user, busy: false });
    } catch (error) {
      clearTokens();
      set({ busy: false, error: messageFor(error) });
      throw error;
    }
  },

  register: async (email, password, name) => {
    set({ busy: true, error: "" });
    try {
      const tokens = await registerAccount(email, password, name);
      saveAccessToken(tokens.access_token);
      const user = await getCurrentUser();
      set({ user, busy: false });
    } catch (error) {
      clearTokens();
      set({ busy: false, error: messageFor(error) });
      throw error;
    }
  },

  finishOAuth: async (code) => {
    set({ busy: true, error: "" });
    try {
      const tokens = await exchangeOAuthCode(code);
      saveAccessToken(tokens.access_token);
      const user = await getCurrentUser();
      set({ user, busy: false });
    } catch (error) {
      clearTokens();
      set({ busy: false, error: messageFor(error) });
      throw error;
    }
  },

  logout: async () => {
    set({ user: null, error: "" });
    try {
      await logoutAccount();
    } finally {
      clearTokens();
    }
  },

  clearError: () => set({ error: "" }),
}));

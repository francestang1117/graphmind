const ACCESS_KEY = "graphmind.accessToken";
// Refresh tokens moved to an HttpOnly cookie. Remove the old key on sign-out
// for anyone who used the earlier localStorage version.
const REFRESH_KEY = "graphmind.refreshToken";

export const AUTH_SESSION_CHANGED_EVENT = "graphmind:auth-session-changed";

let sessionVersion = 0;
let logoutInProgress = false;

function announceSessionChange() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT));
  }
}

export function getSessionVersion() {
  return sessionVersion;
}

export function beginSessionTransition() {
  sessionVersion += 1;
  announceSessionChange();
  return sessionVersion;
}

export function beginLogout() {
  logoutInProgress = true;
  return beginSessionTransition();
}

export function finishLogout() {
  logoutInProgress = false;
}

export function isLogoutInProgress() {
  return logoutInProgress;
}

export function getAccessToken() {
  return localStorage.getItem(ACCESS_KEY);
}

export function saveAccessToken(accessToken: string) {
  localStorage.setItem(ACCESS_KEY, accessToken);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

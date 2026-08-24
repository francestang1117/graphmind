const ACCESS_KEY = "graphmind.accessToken";
// Refresh tokens moved to an HttpOnly cookie. Remove the old key on sign-out
// for anyone who used the earlier localStorage version.
const REFRESH_KEY = "graphmind.refreshToken";

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

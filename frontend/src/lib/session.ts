export const authExpiredEvent = "dataset-gen-auth-expired";
export const authTokenRefreshedEvent = "dataset-gen-auth-token-refreshed";
export const sessionExpiredMessage = "登录已过期，请重新登录。";
const legacyTokenStorageKey = "dataset-gen-token";

export function clearLegacyToken() {
  localStorage.removeItem(legacyTokenStorageKey);
}

export function notifyAuthExpired(message = sessionExpiredMessage) {
  clearLegacyToken();
  window.dispatchEvent(
    new CustomEvent(authExpiredEvent, {
      detail: { message },
    }),
  );
}

export function notifyAuthTokenRefreshed(token: string) {
  window.dispatchEvent(new CustomEvent(authTokenRefreshedEvent, { detail: { token } }));
}

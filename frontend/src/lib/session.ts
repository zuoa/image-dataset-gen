export const authExpiredEvent = "dataset-gen-auth-expired";
export const tokenStorageKey = "dataset-gen-token";
export const sessionExpiredMessage = "登录已过期，请重新登录。";

export function notifyAuthExpired(message = sessionExpiredMessage) {
  localStorage.removeItem(tokenStorageKey);
  window.dispatchEvent(
    new CustomEvent(authExpiredEvent, {
      detail: { message },
    }),
  );
}

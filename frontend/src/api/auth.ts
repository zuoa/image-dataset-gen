import { apiRequest } from "./client";
import type { User } from "../lib/types";

type AuthResponse = {
  token: string;
  user: User;
};

export type LoginCaptcha = {
  captchaId: string;
  image: string;
  expiresIn: number;
};

export function getLoginCaptcha(signal?: AbortSignal) {
  return apiRequest<LoginCaptcha>("/auth/captcha", { signal, skipAuthRefresh: true });
}

export function login(username: string, password: string, captchaId: string, captchaCode: string) {
  return apiRequest<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password, captchaId, captchaCode }),
    skipAuthRefresh: true,
  });
}

export function getMe(token: string) {
  return apiRequest<{ user: User }>("/auth/me", { token });
}

export function refreshSession() {
  return apiRequest<AuthResponse>("/auth/refresh", { method: "POST", skipAuthRefresh: true });
}

export function logout() {
  return apiRequest<{ loggedOut: boolean }>("/auth/logout", { method: "POST", skipAuthRefresh: true });
}

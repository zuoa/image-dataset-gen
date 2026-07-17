import { apiRequest } from "./client";
import type { User } from "../lib/types";

type AuthResponse = {
  token: string;
  user: User;
};

export function login(username: string, password: string) {
  return apiRequest<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
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

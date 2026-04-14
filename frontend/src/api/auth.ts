import { apiRequest } from "./client";
import type { User } from "../lib/types";

type AuthResponse = {
  token: string;
  user: User;
};

export function login(email: string, password: string) {
  return apiRequest<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function register(email: string, password: string) {
  return apiRequest<AuthResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function getMe(token: string) {
  return apiRequest<{ user: User }>("/auth/me", { token });
}

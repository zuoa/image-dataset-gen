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
  });
}

export function getMe(token: string) {
  return apiRequest<{ user: User }>("/auth/me", { token });
}

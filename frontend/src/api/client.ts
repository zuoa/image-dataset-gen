import { notifyAuthExpired, sessionExpiredMessage } from "../lib/session";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

type RequestOptions = RequestInit & {
  token?: string | null;
};

async function parseErrorMessage(response: Response) {
  const errorText = await response.text();
  if (!errorText) {
    return `Request failed with ${response.status}`;
  }

  try {
    const parsed = JSON.parse(errorText) as { msg?: string; message?: string };
    return parsed.msg || parsed.message || errorText;
  } catch {
    return errorText;
  }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    const errorMessage = await parseErrorMessage(response);
    if (response.status === 401) {
      notifyAuthExpired(errorMessage || sessionExpiredMessage);
      throw new Error(errorMessage || sessionExpiredMessage);
    }
    throw new Error(errorMessage);
  }
  return response.json() as Promise<T>;
}

export async function apiRequestFormData<T>(
  path: string,
  body: FormData,
  options: Omit<RequestOptions, "body"> = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    method: options.method ?? "POST",
    body,
    headers,
  });
  if (!response.ok) {
    const errorMessage = await parseErrorMessage(response);
    if (response.status === 401) {
      notifyAuthExpired(errorMessage || sessionExpiredMessage);
      throw new Error(errorMessage || sessionExpiredMessage);
    }
    throw new Error(errorMessage);
  }
  return response.json() as Promise<T>;
}

export function resolveApiUrl(path: string) {
  if (path.startsWith("http://") || path.startsWith("https://") || path.startsWith("data:")) {
    return path;
  }
  if (path.startsWith("/")) {
    const origin = new URL(API_BASE_URL).origin;
    return `${origin}${path}`;
  }
  return `${API_BASE_URL}/${path}`;
}

export async function downloadWithToken(path: string, token: string, filename: string) {
  const response = await fetch(resolveApiUrl(path), {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  if (!response.ok) {
    const errorMessage = await parseErrorMessage(response);
    if (response.status === 401) {
      notifyAuthExpired(errorMessage || sessionExpiredMessage);
      throw new Error(errorMessage || sessionExpiredMessage);
    }
    throw new Error(errorMessage || `Download failed with ${response.status}`);
  }

  const blob = await response.blob();
  const blobUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(blobUrl);
}

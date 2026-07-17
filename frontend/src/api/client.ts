import { notifyAuthExpired, notifyAuthTokenRefreshed, sessionExpiredMessage } from "../lib/session";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

type RequestOptions = RequestInit & {
  token?: string | null;
  skipAuthRefresh?: boolean;
};

let accessRefreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (accessRefreshPromise) return accessRefreshPromise;
  accessRefreshPromise = fetch(buildApiUrl("/auth/refresh"), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  })
    .then(async (response) => {
      if (!response.ok) return null;
      const payload = (await response.json()) as { token?: string };
      if (!payload.token) return null;
      notifyAuthTokenRefreshed(payload.token);
      return payload.token;
    })
    .catch(() => null)
    .finally(() => {
      accessRefreshPromise = null;
    });
  return accessRefreshPromise;
}

async function fetchWithAuthRefresh(path: string, options: RequestOptions, headers: Headers) {
  const { token, skipAuthRefresh, ...requestOptions } = options;
  const execute = () => fetch(buildApiUrl(path), {
    ...requestOptions,
    credentials: requestOptions.credentials ?? "include",
    headers,
  });
  let response = await execute();
  if (response.status !== 401 || !token || skipAuthRefresh) return response;

  const nextToken = await refreshAccessToken();
  if (!nextToken) return response;
  headers.set("Authorization", `Bearer ${nextToken}`);
  response = await execute();
  return response;
}

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

  const response = await fetchWithAuthRefresh(path, options, headers);
  if (!response.ok) {
    const errorMessage = await parseErrorMessage(response);
    if (response.status === 401 && !options.skipAuthRefresh) {
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

  const response = await fetchWithAuthRefresh(path, {
    ...options,
    method: options.method ?? "POST",
    body,
  }, headers);
  if (!response.ok) {
    const errorMessage = await parseErrorMessage(response);
    if (response.status === 401 && !options.skipAuthRefresh) {
      notifyAuthExpired(errorMessage || sessionExpiredMessage);
      throw new Error(errorMessage || sessionExpiredMessage);
    }
    throw new Error(errorMessage);
  }
  return response.json() as Promise<T>;
}

function apiOrigin() {
  if (typeof window === "undefined") {
    return "";
  }
  return window.location.origin;
}

function normalizedApiBaseUrl() {
  if (API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://")) {
    return API_BASE_URL.replace(/\/$/, "");
  }
  return `${apiOrigin()}${API_BASE_URL.startsWith("/") ? "" : "/"}${API_BASE_URL}`.replace(/\/$/, "");
}

function buildApiUrl(path: string) {
  return `${normalizedApiBaseUrl()}${path.startsWith("/") ? "" : "/"}${path}`;
}

export function resolveApiUrl(path: string) {
  if (path.startsWith("http://") || path.startsWith("https://") || path.startsWith("data:")) {
    return path;
  }
  if (path.startsWith("/")) {
    return `${apiOrigin()}${path}`;
  }
  return `${normalizedApiBaseUrl()}/${path}`;
}

export async function downloadWithToken(path: string, token: string, filename: string) {
  const headers = new Headers({ Authorization: `Bearer ${token}` });
  let response = await fetch(resolveApiUrl(path), { headers, credentials: "include" });
  if (response.status === 401) {
    const nextToken = await refreshAccessToken();
    if (nextToken) {
      headers.set("Authorization", `Bearer ${nextToken}`);
      response = await fetch(resolveApiUrl(path), { headers, credentials: "include" });
    }
  }
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

export async function fetchTextWithToken(path: string, token: string) {
  const headers = new Headers({ Authorization: `Bearer ${token}` });
  let response = await fetch(resolveApiUrl(path), { headers, credentials: "include" });
  if (response.status === 401) {
    const nextToken = await refreshAccessToken();
    if (nextToken) {
      headers.set("Authorization", `Bearer ${nextToken}`);
      response = await fetch(resolveApiUrl(path), { headers, credentials: "include" });
    }
  }
  if (!response.ok) {
    const errorMessage = await parseErrorMessage(response);
    if (response.status === 401) {
      notifyAuthExpired(errorMessage || sessionExpiredMessage);
      throw new Error(errorMessage || sessionExpiredMessage);
    }
    throw new Error(errorMessage || `Request failed with ${response.status}`);
  }

  return response.text();
}

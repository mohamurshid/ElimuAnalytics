/**
 * The API client.
 *
 * Holds the access token in a module variable - in memory, never in
 * `localStorage`. Anything in storage is readable by any script that gets
 * injected into the page, and these accounts reach children's assessment
 * records. The cost of that choice is that the token dies on reload, which is
 * what the refresh cookie exists to repair.
 *
 * Three behaviours worth knowing before reading the code:
 *
 * **Every call retries once after a 401.** The access token lives fifteen
 * minutes, so expiry during an ordinary session is normal rather than
 * exceptional. The client refreshes and repeats the request, and the caller
 * never sees it.
 *
 * **Concurrent refreshes are collapsed into one.** A dashboard fires several
 * requests at once; if the token has just expired they all get a 401 at the
 * same moment. Refreshing per request would spend several single-use tokens
 * simultaneously, and rotation would read the second one as a replay and
 * revoke the whole family - signing the teacher out for being busy. So the
 * first refresh is stored as a promise and the rest await it.
 *
 * **`credentials: "include"` on every request.** The refresh cookie is
 * httpOnly, so script cannot attach it; the browser does, but only if asked.
 */

import type { LoginResponse, Profile } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

async function readError(response: globalThis.Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (detail) return JSON.stringify(detail);
  } catch {
    // no JSON body; fall through to the status text
  }
  return response.statusText || `HTTP ${response.status}`;
}

async function send(
  path: string,
  init: RequestInit,
): Promise<globalThis.Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body) headers.set("Content-Type", "application/json");
  return fetch(path, { ...init, headers, credentials: "include" });
}

/**
 * Exchange the refresh cookie for a new access token.
 *
 * Shared: callers that arrive while one is in flight wait for it rather than
 * starting their own, because the refresh token is single-use and spending
 * two at once looks like a replay to the server.
 */
export function refresh(): Promise<boolean> {
  if (refreshing) return refreshing;

  refreshing = (async () => {
    try {
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) {
        accessToken = null;
        return false;
      }
      const body: LoginResponse = await response.json();
      accessToken = body.access_token;
      return true;
    } catch {
      accessToken = null;
      return false;
    } finally {
      refreshing = null;
    }
  })();

  return refreshing;
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
  { retry = true }: { retry?: boolean } = {},
): Promise<T> {
  let response = await send(path, init);

  if (response.status === 401 && retry) {
    // Ordinary: the fifteen-minute token expired mid-session.
    const renewed = await refresh();
    if (renewed) {
      response = await send(path, init);
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readError(response));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/** Sign in. Sets the refresh cookie server-side; returns the access token. */
export async function login(
  email: string,
  password: string,
): Promise<LoginResponse> {
  // No retry: a 401 here means the password is wrong, and refreshing would
  // be nonsense.
  const body = await request<LoginResponse>(
    "/api/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
    { retry: false },
  );
  accessToken = body.access_token;
  return body;
}

export async function logout(): Promise<void> {
  try {
    await request("/api/auth/logout", { method: "POST" }, { retry: false });
  } finally {
    // Whatever the server said, this session is over on this device.
    accessToken = null;
  }
}

export const getProfile = () => api.get<Profile>("/api/auth/me");

/** Human-readable text for anything thrown by the client. */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

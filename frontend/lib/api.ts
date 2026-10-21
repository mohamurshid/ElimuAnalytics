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

    // The batch endpoints answer with {problems: [...], reason?: "..."}. The
    // list can run to dozens of entries naming UUIDs, which is useful in a
    // log and unreadable on screen, so the reason leads and the problems are
    // summarised. Dumping the raw JSON into the interface - which this did -
    // tells a teacher nothing they can act on.
    if (detail && typeof detail === "object") {
      const problems: string[] = Array.isArray(detail.problems)
        ? detail.problems
        : [];
      const reason: string | undefined = detail.reason;
      if (reason || problems.length) {
        const count =
          problems.length > 1 ? ` (${problems.length} items affected)` : "";
        return [reason ?? problems[0], count].filter(Boolean).join("").trim();
      }
      return JSON.stringify(detail);
    }
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

/**
 * Set your own password with a head teacher's one-time code. Like login, it
 * signs this device in: the server sets the refresh cookie and returns an
 * access token.
 */
export async function setupAccount(
  email: string,
  code: string,
  password: string,
): Promise<LoginResponse> {
  const body = await request<LoginResponse>(
    "/api/auth/setup",
    { method: "POST", body: JSON.stringify({ email, code, password }) },
    { retry: false },
  );
  accessToken = body.access_token;
  return body;
}

/**
 * Change your password. Every other device is signed out; this one is given
 * a fresh session, whose access token replaces the old one here.
 */
export async function changePassword(current: string, next: string): Promise<void> {
  const body = await request<LoginResponse>("/api/auth/password", {
    method: "POST",
    body: JSON.stringify({ current_password: current, new_password: next }),
  });
  accessToken = body.access_token;
}

/** End every session on every device, this one included. */
export async function logoutEverywhere(): Promise<void> {
  try {
    await request("/api/auth/logout-everywhere", { method: "POST" }, { retry: false });
  } finally {
    accessToken = null;
  }
}

export const getProfile = () => api.get<Profile>("/api/auth/me");

/** The filename the server chose, so a download is not called "report.pdf". */
function filenameFrom(header: string | null): string {
  const match = header?.match(/filename="([^"]+)"/);
  return match ? match[1] : "report.pdf";
}

/**
 * Fetch a file rather than JSON.
 *
 * A plain `<a href>` to a download endpoint would arrive unauthenticated:
 * the access token is held in memory, not in a cookie, which is the whole
 * reason this client exists. So the file comes back through the same path as
 * every other request - including the retry after a 401, because a token
 * expiring in the second before a teacher clicks Download is ordinary.
 */
export async function downloadFile(
  path: string,
): Promise<{ blob: Blob; filename: string }> {
  let response = await send(path, {});

  if (response.status === 401) {
    const renewed = await refresh();
    if (renewed) response = await send(path, {});
  }
  if (!response.ok) {
    throw new ApiError(response.status, await readError(response));
  }

  return {
    blob: await response.blob(),
    filename: filenameFrom(response.headers.get("content-disposition")),
  };
}

/** Human-readable text for anything thrown by the client. */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

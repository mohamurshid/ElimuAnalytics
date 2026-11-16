/**
 * Answers not yet saved, kept on this device (29 October).
 *
 * Both quiz screens (and, since 16 November, the observation grid) hold a
 * class's work in the page until the teacher saves
 * it: a device quiz until the session ends, paper marks until Submit. A
 * dropped connection at that moment, a reload, or a phone that dies took all
 * of it with them. Now every answer is also written here as it is given, and
 * removed only when the server has confirmed it.
 *
 * **Safe to send twice.** The batch keeps the client_batch_id it was created
 * with, so a save that reached the server before the connection dropped is
 * recognised as the same batch when it is sent again - never recorded twice.
 *
 * **What is stored is the least that can be.** Learner and question ids and
 * the option chosen (or right / wrong): no names, no answer key, nothing a
 * learner could read the answers from. It belongs to the teacher who made
 * it - another teacher signed in on the same device is not shown it - and it
 * is dropped after seven days, by which time it is no longer a quiz anyone
 * would record.
 *
 * Browser storage can be unavailable (private windows, full storage); every
 * call here fails quietly and the page works as it did before, in memory.
 */

import { ApiError } from "@/lib/api";

export type PendingKind = "device" | "paper" | "observe";

export type PendingBatch<R> = {
  v: 1;
  kind: PendingKind;
  teacherId: string;
  classId: string;
  strandId: string;
  /** Paper only: the quiz whose grid this is, so marking can carry on. */
  quizId?: string;
  /** Observe only: the observed task these levels belong to. */
  taskId?: string;
  batchId: string;
  responses: R[];
  /** Learners with at least one answer, for the sentence shown. */
  learners: number;
  savedAt: number;
};

const PREFIX = "elimu.pending.";
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

const storageKey = (kind: PendingKind, classId: string) => `${PREFIX}${kind}.${classId}`;

export function savePending<R>(batch: Omit<PendingBatch<R>, "v" | "savedAt">): void {
  try {
    if (batch.responses.length === 0) {
      localStorage.removeItem(storageKey(batch.kind, batch.classId));
      return;
    }
    const full: PendingBatch<R> = { ...batch, v: 1, savedAt: Date.now() };
    localStorage.setItem(storageKey(batch.kind, batch.classId), JSON.stringify(full));
  } catch {
    // Storage unavailable: the answers are still held in the page.
  }
}

export function readPending<R>(
  kind: PendingKind,
  classId: string,
  teacherId: string | undefined,
): PendingBatch<R> | null {
  if (!teacherId) return null;
  try {
    const raw = localStorage.getItem(storageKey(kind, classId));
    if (!raw) return null;
    const batch = JSON.parse(raw) as PendingBatch<R>;
    if (batch.v !== 1 || !Array.isArray(batch.responses) || !batch.batchId) {
      localStorage.removeItem(storageKey(kind, classId));
      return null;
    }
    if (Date.now() - batch.savedAt > MAX_AGE_MS) {
      localStorage.removeItem(storageKey(kind, classId));
      return null;
    }
    // Another teacher's work on a shared device: not shown, not deleted.
    if (batch.teacherId !== teacherId) return null;
    return batch.responses.length > 0 ? batch : null;
  } catch {
    return null;
  }
}

export function clearPending(kind: PendingKind, classId: string): void {
  try {
    localStorage.removeItem(storageKey(kind, classId));
  } catch {
    // Nothing to clear.
  }
}

/**
 * A version 4 UUID. `crypto.randomUUID` exists only on secure origins, and
 * a phone reaching the laptop by its network address is not one; the old
 * fallback was not a UUID at all, so the server refused every save made that
 * way. `getRandomValues` works on any origin.
 */
export function newBatchId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    try {
      return crypto.randomUUID();
    } catch {
      // Insecure origin: fall through.
    }
  }
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/**
 * Worth sending again: the request never arrived or the server failed. A
 * refusal (4xx) is an answer, and sending it again would only repeat it.
 */
export function isRetryable(e: unknown): boolean {
  if (!(e instanceof ApiError)) return true; // fetch threw: no connection
  return e.status >= 500 || e.status === 408 || e.status === 429;
}

/** Send, and on a dropped connection try twice more, a little apart. */
export async function sendWithRetry<T>(send: () => Promise<T>): Promise<T> {
  const waits = [1500, 4000];
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await send();
    } catch (e) {
      if (attempt >= waits.length || !isRetryable(e)) throw e;
      await new Promise((r) => setTimeout(r, waits[attempt]));
    }
  }
}

/** "3 learners' answers from 10:42 today" - for the not-yet-saved card. */
export function describePending(batch: PendingBatch<unknown>, what: string): string {
  const when = new Date(batch.savedAt);
  const today = new Date().toDateString() === when.toDateString();
  const time = when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const day = today ? "today" : when.toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });
  const n = batch.learners;
  return `${n} ${n === 1 ? "learner’s" : "learners’"} ${what} from ${time} ${day}`;
}

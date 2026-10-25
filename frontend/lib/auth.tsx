"use client";

/**
 * Who is signed in, for the rest of the app.
 *
 * The state machine has three states, and conflating the first two is the
 * classic bug in this pattern:
 *
 *   "unknown"  - the page just loaded; we are asking the refresh cookie
 *   "guest"    - asked, and there is no session
 *   "signed in"
 *
 * On a reload the access token is gone, because it was only ever in memory.
 * The refresh cookie survives, so the app asks the server first. Until that
 * answer arrives the app does not know whether the teacher is signed in, and
 * a guard that treats "unknown" as "guest" will bounce a perfectly valid
 * session to the login page for a fraction of a second on every reload.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  changePassword as apiChangePassword,
  getProfile,
  login as apiLogin,
  logout as apiLogout,
  logoutEverywhere,
  refresh,
  setupAccount,
} from "./api";
import type { Profile } from "./types";

type AuthState = {
  /** Null once resolved and nobody is signed in. */
  profile: Profile | null;
  /** False until the refresh cookie has been asked. Guards must wait on this. */
  resolved: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  /** First sign-in with a head teacher's setup code. */
  setUp: (email: string, code: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Every device, this one included. */
  signOutEverywhere: () => Promise<void>;
  /** Change the password, or set a first one with `current` null; the profile
   *  is read back so `has_password` is current everywhere. */
  changePassword: (current: string | null, next: string) => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [resolved, setResolved] = useState(false);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      // The access token died with the previous page. The cookie did not.
      const renewed = await refresh();
      if (cancelled) return;
      if (!renewed) {
        setResolved(true);
        return;
      }
      try {
        const me = await getProfile();
        if (!cancelled) setProfile(me);
      } catch {
        if (!cancelled) setProfile(null);
      } finally {
        if (!cancelled) setResolved(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    await apiLogin(email, password);
    // Read the account back rather than trusting the login response: the same
    // reasoning as the backend re-resolving the role on every request.
    setProfile(await getProfile());
    setResolved(true);
  }, []);

  const setUp = useCallback(async (email: string, code: string, password: string) => {
    await setupAccount(email, code, password);
    setProfile(await getProfile());
    setResolved(true);
  }, []);

  const signOut = useCallback(async () => {
    await apiLogout();
    setProfile(null);
    setResolved(true);
  }, []);

  const signOutEverywhere = useCallback(async () => {
    await logoutEverywhere();
    setProfile(null);
    setResolved(true);
  }, []);

  const changePassword = useCallback(async (current: string | null, next: string) => {
    await apiChangePassword(current, next);
    setProfile(await getProfile());
  }, []);

  const value = useMemo(
    () => ({ profile, resolved, signIn, setUp, signOut, signOutEverywhere, changePassword }),
    [profile, resolved, signIn, setUp, signOut, signOutEverywhere, changePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}

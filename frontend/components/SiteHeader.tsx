"use client";

/**
 * The public pages' header: the landing page, sign-in and set-up (25
 * October). One header, so moving between them never loses the way back to
 * the explanation or across to the other door.
 *
 * On a phone there is room for one button: the page you are NOT on (set up
 * from sign-in, sign in from set-up and from the landing page). A signed-in
 * teacher is offered the app instead.
 */

import Link from "next/link";

import { Icon } from "@/components/Icon";
import { Logo } from "@/components/Logo";
import { useAuth } from "@/lib/auth";
import { HOME } from "@/lib/routes";

type Page = "home" | "login" | "setup";

// No display class here: each link adds its own, so "hidden" on a phone is
// never fighting an inline-flex in the same class list.
const PILL = "min-h-10 items-center gap-1 whitespace-nowrap rounded-full px-4 text-sm font-semibold transition-colors";
const SOLID = `${PILL} bg-action text-action-ink hover:bg-action-hover`;
const PLAIN = `${PILL} text-ink hover:bg-sunken`;

export function SiteHeader({ current = "home" }: { current?: Page }) {
  const { profile, resolved } = useAuth();
  const signedIn = resolved && profile !== null;

  return (
    <header className="sticky top-0 z-30 border-b border-line/70 bg-canvas/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" aria-label="Elimu Analytics, home" className="shrink-0 whitespace-nowrap">
          <Logo />
        </Link>
        <nav aria-label="About Elimu Analytics" className="hidden items-center gap-6 text-sm font-medium text-ink-muted md:flex">
          <Link href="/#why" className="hover:text-ink">Why IRT</Link>
          <Link href="/#curve" className="hover:text-ink">How a question behaves</Link>
          <Link href="/#how" className="hover:text-ink">How it works</Link>
        </nav>
        {signedIn ? (
          <Link href={HOME} className={`${SOLID} inline-flex`}>
            Open Elimu <Icon name="chevronRight" className="size-4" />
          </Link>
        ) : (
          <div className="flex items-center gap-1.5">
            <Link
              href="/login"
              aria-current={current === "login" ? "page" : undefined}
              className={`${PLAIN} ${current === "login" ? "hidden bg-sunken sm:inline-flex" : "inline-flex"}`}
            >
              Sign in
            </Link>
            <Link
              href="/setup"
              aria-current={current === "setup" ? "page" : undefined}
              className={`${SOLID} ${current === "login" ? "inline-flex" : "hidden sm:inline-flex"}`}
            >
              Set up account
            </Link>
          </div>
        )}
      </div>
    </header>
  );
}

"use client";

/**
 * Navigation: a top bar everywhere, and a bottom tab bar on phones.
 *
 * On a phone the three destinations live at the bottom of the screen, where
 * a thumb reaches them. The previous single row put brand, three links, the
 * teacher's name, their role and a sign-out button side by side; at phone
 * width that wrapped into "Elimu / Analytics" and "Demo / Teacher /
 * (teacher)" stacked three high.
 *
 * Labels are a teacher's words, not the code's: "Support" rather than
 * "Intervention queue", "Classes" rather than "Classrooms".
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/Logo";
import { useAuth } from "@/lib/auth";
import { initials, ROLE_LABEL } from "@/lib/people";
import { HOME } from "@/lib/routes";

function SupportIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="9" cy="8" r="3.25" />
      <path d="M3.5 19.5c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5" />
      <path d="M18 8v6M15 11h6" />
    </svg>
  );
}

function ClassesIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M3.5 9.5h17M9.5 9.5v10" />
    </svg>
  );
}

function OverviewIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 19.5h16" />
      <path d="M7 16V11M12 16V6.5M17 16v-3" />
    </svg>
  );
}

const LINKS = [
  { href: HOME, label: "Support", Icon: SupportIcon },
  { href: "/classrooms", label: "Classes", Icon: ClassesIcon },
  { href: "/dashboard", label: "Overview", Icon: OverviewIcon },
];

function useActive() {
  const pathname = usePathname();
  // Learner pages are reached from a class, so they light up Classes.
  return (href: string) =>
    pathname.startsWith(href) ||
    (href === "/classrooms" && pathname.startsWith("/students"));
}

export function TopBar() {
  const { profile } = useAuth();
  const isActive = useActive();
  const onProfile = usePathname().startsWith("/profile");

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur print:hidden">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-4 px-4">
        <Link href={HOME} className="min-h-11 inline-flex items-center" aria-label="Elimu Analytics home">
          <Logo />
        </Link>

        {/* Wide screens: the destinations sit in the bar itself. */}
        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {LINKS.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(href) ? "page" : undefined}
              className={`inline-flex min-h-11 items-center rounded-md px-3 text-[15px]
                          ${isActive(href)
                            ? "bg-sunken font-medium text-ink"
                            : "text-ink-muted hover:text-ink"}`}
            >
              {label}
            </Link>
          ))}
        </nav>

        {/* Initials, the pattern every phone user already knows. Sign-out
            moved into the profile page, one tap further away - and placed at
            the top of it, because school devices are shared. */}
        <Link
          href="/profile"
          aria-label={profile ? `Your profile: ${profile.name}` : "Your profile"}
          aria-current={onProfile ? "page" : undefined}
          className="-mr-1 flex min-h-11 items-center gap-3 rounded-md px-1 hover:bg-sunken"
        >
          {profile && (
            <span className="hidden text-right leading-tight md:block">
              <span className="block text-sm font-medium text-ink">{profile.name}</span>
              <span className="block text-xs text-ink-subtle">
                {ROLE_LABEL[profile.role] ?? profile.role}
              </span>
            </span>
          )}
          <span
            aria-hidden="true"
            className={`flex size-9 items-center justify-center rounded-full border text-sm
                        font-semibold text-ink
                        ${onProfile ? "border-ink bg-sunken" : "border-line-strong bg-sunken"}`}
          >
            {initials(profile?.name)}
          </span>
        </Link>
      </div>
    </header>
  );
}

/** Phones only. Hidden from md upwards, where the top bar carries the links. */
export function BottomNav() {
  const isActive = useActive();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface/95
                 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden print:hidden"
    >
      <ul className="mx-auto grid max-w-md grid-cols-3">
        {LINKS.map(({ href, label, Icon }) => {
          const active = isActive(href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={`relative flex min-h-16 flex-col items-center justify-center gap-1
                            text-xs font-medium
                            ${active ? "text-ink" : "text-ink-subtle hover:text-ink-muted"}`}
              >
                {active && (
                  <span aria-hidden="true"
                        className="absolute inset-x-6 top-0 h-0.5 rounded-full bg-ink" />
                )}
                <Icon />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

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

import { Icon, type IconName } from "@/components/Icon";
import { Logo } from "@/components/Logo";
import { useAuth } from "@/lib/auth";
import { initials, ROLE_LABEL } from "@/lib/people";
import { HOME } from "@/lib/routes";

const LINKS: { href: string; label: string; icon: IconName }[] = [
  { href: HOME, label: "Support", icon: "support" },
  { href: "/classrooms", label: "Classes", icon: "classes" },
  { href: "/dashboard", label: "Overview", icon: "overview" },
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
    <header className="sticky top-0 z-20 border-b border-line bg-surface/90 backdrop-blur-md print:hidden">
      <div className="mx-auto flex h-16 max-w-5xl items-center justify-between gap-4 px-4">
        <Link href={HOME} className="inline-flex min-h-11 items-center" aria-label="Elimu Analytics home">
          <Logo />
        </Link>

        {/* Wide screens: the destinations sit in the bar itself. */}
        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {LINKS.map(({ href, label, icon }) => {
            const active = isActive(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`inline-flex min-h-11 items-center gap-2 rounded-xl px-3.5 text-[15px] font-semibold transition-colors
                            ${active
                              ? "bg-brand-fill text-brand-strong"
                              : "text-ink-muted hover:bg-sunken hover:text-ink"}`}
              >
                <Icon name={icon} className="size-5" />
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Initials, the pattern every phone user already knows. Sign-out
            lives at the top of the profile page, because school devices are
            shared. */}
        <Link
          href="/profile"
          aria-label={profile ? `Your profile: ${profile.name}` : "Your profile"}
          aria-current={onProfile ? "page" : undefined}
          className="-mr-1 flex min-h-11 items-center gap-3 rounded-xl px-1.5 hover:bg-sunken"
        >
          {profile && (
            <span className="hidden text-right leading-tight md:block">
              <span className="block text-sm font-semibold text-ink">{profile.name}</span>
              <span className="block text-xs text-ink-subtle">
                {ROLE_LABEL[profile.role] ?? profile.role}
              </span>
            </span>
          )}
          <span
            aria-hidden="true"
            className={`flex size-10 items-center justify-center rounded-full text-sm font-bold
                        ${onProfile
                          ? "bg-action text-action-ink"
                          : "bg-brand-fill text-brand-strong"}`}
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
                 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden print:hidden"
    >
      <ul className="mx-auto grid max-w-md grid-cols-3">
        {LINKS.map(({ href, label, icon }) => {
          const active = isActive(href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-16 flex-col items-center justify-center gap-1 text-xs font-semibold
                            ${active ? "text-brand-strong" : "text-ink-subtle hover:text-ink-muted"}`}
              >
                {/* The active tab's icon sits in a pill, as in Android's own
                    navigation bar - the pattern a phone user already reads. */}
                <span
                  className={`flex h-8 w-14 items-center justify-center rounded-full transition-colors
                              ${active ? "bg-brand-fill" : ""}`}
                >
                  <Icon name={icon} className="size-6" />
                </span>
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

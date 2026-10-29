/**
 * The app's icons: simple 24px line drawings, drawn here rather than pulled
 * from a package, so there is nothing to install and nothing extra to load.
 * Decorative by default (aria-hidden); the label beside an icon says what it
 * means, because an icon alone never should.
 */

const PATHS = {
  support: (
    <>
      <circle cx="9" cy="8" r="3.25" />
      <path d="M3.5 19.5c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5" />
      <path d="M18 8v6M15 11h6" />
    </>
  ),
  classes: (
    <>
      <circle cx="8.5" cy="8.5" r="3" />
      <circle cx="16.5" cy="9.5" r="2.5" />
      <path d="M3 19c.5-3 2.7-4.8 5.5-4.8s5 1.8 5.5 4.8M14.5 14.6c2.6-.3 5.1 1.1 5.9 4.4" />
    </>
  ),
  overview: (
    <>
      <path d="M4 19.5h16" />
      <rect x="5.5" y="11" width="3" height="5.5" rx="1" />
      <rect x="10.5" y="6.5" width="3" height="10" rx="1" />
      <rect x="15.5" y="9" width="3" height="7.5" rx="1" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  lock: (
    <>
      <rect x="5" y="10.5" width="14" height="9.5" rx="2.5" />
      <path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c.7-3.6 3.5-5.5 7-5.5s6.3 1.9 7 5.5" />
    </>
  ),
  hand: (
    <>
      <path d="M8 13V6.5a1.5 1.5 0 0 1 3 0V12" />
      <path d="M11 11V5a1.5 1.5 0 0 1 3 0v6" />
      <path d="M14 11V6.5a1.5 1.5 0 0 1 3 0V14c0 3.6-2.4 6-5.6 6-2.2 0-3.6-.9-4.9-2.6L4.6 13.6a1.5 1.5 0 0 1 2.3-1.9L8 13" />
    </>
  ),
  chevronRight: <path d="M9.5 6l6 6-6 6" />,
  chevronLeft: <path d="M14.5 6l-6 6 6 6" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  sparkles: (
    <>
      <path d="M11 4l1.6 4.4L17 10l-4.4 1.6L11 16l-1.6-4.4L5 10l4.4-1.6z" />
      <path d="M18 15l.7 1.8 1.8.7-1.8.7L18 20l-.7-1.8-1.8-.7 1.8-.7z" />
    </>
  ),
  phone: (
    <>
      <rect x="7" y="3" width="10" height="18" rx="2.5" />
      <path d="M11 17.5h2" />
    </>
  ),
  paper: (
    <>
      <path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10.5a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5z" />
      <path d="M14 3.5V8h4M9.5 12.5l1.5 1.5 3-3M9.5 17h5" />
    </>
  ),
  save: (
    <>
      <path d="M5 4.5h11l3 3V19a.5.5 0 0 1-.5.5h-13A.5.5 0 0 1 5 19z" />
      <path d="M8.5 4.5v4h6v-4M8 19.5v-5h8v5" />
    </>
  ),
  refresh: (
    <>
      <path d="M19 8a7.5 7.5 0 0 0-13.4-1.6M5 4.5v3.4h3.4" />
      <path d="M5 16a7.5 7.5 0 0 0 13.4 1.6M19 19.5v-3.4h-3.4" />
    </>
  ),
  users: (
    <>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c.7-3.6 3.5-5.5 7-5.5s6.3 1.9 7 5.5" />
    </>
  ),
  book: (
    <>
      <path d="M4 5.5c2.5-1 5.3-1 8 .5v13.5c-2.7-1.5-5.5-1.5-8-.5z" />
      <path d="M20 5.5c-2.5-1-5.3-1-8 .5v13.5c2.7-1.5 5.5-1.5 8-.5z" />
    </>
  ),
  calendar: (
    <>
      <rect x="4" y="5" width="16" height="15" rx="2.5" />
      <path d="M4 9.5h16M8.5 3v4M15.5 3v4" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5M12 8v.01" />
    </>
  ),
  alert: (
    <>
      <path d="M12 4l9 15.5H3z" />
      <path d="M12 10v4M12 17v.01" />
    </>
  ),
  trend: (
    <>
      <path d="M4 16l5-5 3.5 3.5L20 7" />
      <path d="M15 7h5v5" />
    </>
  ),
  seedling: (
    <>
      <path d="M12 20v-8" />
      <path d="M12 12c0-3.5-2.5-6-6.5-6 0 3.5 2.5 6 6.5 6zM12 13c0-3 2.2-5.5 6.5-5.5 0 3-2.2 5.5-6.5 5.5z" />
    </>
  ),
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({
  name,
  className = "size-5",
  strokeWidth = 1.8,
}: {
  name: IconName;
  className?: string;
  strokeWidth?: number;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}

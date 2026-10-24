"use client";

/**
 * Shared pieces, so pages read as what they do rather than as walls of
 * utility classes.
 *
 * Three rules every component here keeps:
 *
 * **44px minimum touch target.** These are used on phones, often by a teacher
 * standing in front of a class. A 30px button is a miss-and-retry affair.
 *
 * **Colour comes from the tokens in globals.css, never from Tailwind's
 * palette.** The previous version hardcoded bg-white and neutral-900, which
 * is why the header stayed white while the rest of the page went dark.
 *
 * **Inputs are 16px.** Anything smaller makes iOS zoom the page on focus,
 * and the layout then has to be panned back by hand.
 */

import Link from "next/link";

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "md" | "sm";

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-action text-action-ink hover:bg-action-hover border border-transparent",
  secondary:
    "bg-surface text-ink border border-line-strong hover:bg-sunken",
  danger:
    "bg-surface text-risk border border-line-strong hover:bg-risk-fill",
  ghost: "bg-transparent text-ink border border-transparent hover:bg-sunken",
};

// md is the touch size. sm exists for dense rows on wide screens only; it
// never goes below 36px, and pages should not use it in a phone layout.
const SIZE: Record<Size, string> = {
  md: "min-h-11 px-4 text-[15px]",
  sm: "min-h-9 px-3 text-sm",
};

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-md font-medium " +
  "whitespace-nowrap transition-colors disabled:cursor-not-allowed " +
  "disabled:opacity-50";

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
}) {
  return (
    <button
      {...props}
      className={`${BASE} ${VARIANT[variant]} ${SIZE[size]} ${className}`}
    />
  );
}

/** A link that looks like a button - for navigation that reads as an action. */
export function ButtonLink({
  href,
  variant = "secondary",
  size = "md",
  className = "",
  children,
}: {
  href: string;
  variant?: Variant;
  size?: Size;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`${BASE} ${VARIANT[variant]} ${SIZE[size]} ${className}`}
    >
      {children}
    </Link>
  );
}

export function Field({
  label,
  hint,
  error,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: string;
  error?: string | null;
}) {
  const describedBy = error
    ? `${props.id ?? props.name}-error`
    : hint
      ? `${props.id ?? props.name}-hint`
      : undefined;
  return (
    <label className="block">
      <span className="text-sm font-medium text-ink">{label}</span>
      <input
        {...props}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={`mt-1.5 block min-h-11 w-full rounded-md border bg-surface
                    px-3 text-base text-ink placeholder:text-ink-subtle
                    focus:border-ink focus:outline-none
                    ${error ? "border-risk" : "border-line-strong"}`}
      />
      {error ? (
        <span
          id={`${props.id ?? props.name}-error`}
          className="mt-1.5 block text-sm text-risk"
        >
          {error}
        </span>
      ) : hint ? (
        <span
          id={`${props.id ?? props.name}-hint`}
          className="mt-1.5 block text-sm text-ink-subtle"
        >
          {hint}
        </span>
      ) : null}
    </label>
  );
}

type Tone = "info" | "error" | "ok" | "warn";

const TONE: Record<Tone, string> = {
  info: "border-line bg-sunken text-ink",
  error: "border-risk/30 bg-risk-fill text-risk",
  ok: "border-ok/30 bg-ok-fill text-ok",
  warn: "border-warn/30 bg-warn-fill text-warn",
};

export function Note({
  tone = "info",
  children,
}: {
  tone?: Tone;
  children: React.ReactNode;
}) {
  if (!children) return null;
  return (
    <p
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-md border px-3.5 py-3 text-[15px] leading-relaxed
                  ${TONE[tone]}`}
    >
      {children}
    </p>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <p role="status" className="flex items-center gap-2.5 py-6 text-[15px] text-ink-muted">
      <span
        aria-hidden="true"
        className="inline-block size-2 animate-pulse rounded-full bg-ink-subtle"
      />
      Loading {what}…
    </p>
  );
}

/**
 * An empty state is a screen people meet often - the home screen will be one
 * for every teacher until their class has two assessments - so it says what is
 * missing and offers the way forward, rather than just "nothing here".
 */
export function Empty({
  title,
  action,
  children,
}: {
  title?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong px-5 py-10 text-center">
      {title && <p className="text-base font-semibold text-ink">{title}</p>}
      <p className={`mx-auto max-w-sm text-[15px] leading-relaxed text-ink-muted ${title ? "mt-1.5" : ""}`}>
        {children}
      </p>
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  back,
  actions,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  back?: { href: string; label: string };
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-6">
      {back && (
        <Link
          href={back.href}
          className="-ml-1 mb-2 inline-flex min-h-11 items-center gap-1 px-1
                     text-[15px] text-ink-muted hover:text-ink"
        >
          <span aria-hidden="true">‹</span> {back.label}
        </Link>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-[28px]">
            {title}
          </h1>
          {description && (
            <p className="mt-1.5 max-w-prose text-[15px] leading-relaxed text-ink-muted">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex flex-wrap gap-2 sm:shrink-0">{actions}</div>}
      </div>
    </header>
  );
}

export function Card({
  className = "",
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`rounded-lg border border-line bg-surface ${className}`}>
      {children}
    </div>
  );
}

/** System state, never a learner's standing - see the palette rule. */
export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "ok" | "warn" | "risk";
  children: React.ReactNode;
}) {
  const style = {
    neutral: "border-line-strong bg-sunken text-ink-muted",
    ok: "border-ok/30 bg-ok-fill text-ok",
    warn: "border-warn/30 bg-warn-fill text-warn",
    risk: "border-risk/30 bg-risk-fill text-risk",
  }[tone];
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-xs
                  font-semibold uppercase tracking-wide ${style}`}
    >
      {children}
    </span>
  );
}

/** A labelled drop-down at touch size, styled like Field. */
export function Select({
  label,
  hint,
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & {
  label: string;
  hint?: string;
}) {
  return (
    <label className="block min-w-0">
      <span className="text-sm font-medium text-ink">{label}</span>
      <select
        {...props}
        className="mt-1.5 block min-h-11 w-full rounded-md border border-line-strong
                   bg-surface px-3 text-base text-ink focus:border-ink focus:outline-none"
      >
        {children}
      </select>
      {hint && <span className="mt-1.5 block text-sm text-ink-subtle">{hint}</span>}
    </label>
  );
}

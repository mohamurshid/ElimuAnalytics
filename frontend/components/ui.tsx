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
 * palette.** Restyled 29 October for the redesign: rounded, soft shadows,
 * brand-green primary, icons in notes and empty states. Every export and
 * prop kept, so no page had to change to keep working. The previous version hardcoded bg-white and neutral-900, which
 * is why the header stayed white while the rest of the page went dark.
 *
 * **Inputs are 16px.** Anything smaller makes iOS zoom the page on focus,
 * and the layout then has to be panned back by hand.
 */

import Link from "next/link";

import { Icon, type IconName } from "@/components/Icon";

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "md" | "sm";

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-action text-action-ink hover:bg-action-hover border border-transparent shadow-soft",
  secondary:
    "bg-surface text-ink border border-line-strong hover:border-ink-subtle hover:bg-sunken",
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
  "inline-flex items-center justify-center gap-2 rounded-xl font-semibold " +
  "whitespace-nowrap transition-all active:scale-[0.98] disabled:cursor-not-allowed " +
  "disabled:opacity-50 disabled:active:scale-100";

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
        className={`mt-1.5 block min-h-11 w-full rounded-xl border bg-surface
                    px-3.5 text-base text-ink placeholder:text-ink-subtle
                    transition-shadow focus:border-action focus:outline-none
                    focus:ring-4 focus:ring-brand-fill
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
  error: "border-risk/25 bg-risk-fill text-risk",
  ok: "border-ok/25 bg-ok-fill text-ok",
  warn: "border-warn/25 bg-warn-fill text-warn",
};

const TONE_ICON: Record<Tone, IconName> = {
  info: "info",
  error: "alert",
  ok: "check",
  warn: "alert",
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
      className={`flex gap-2.5 rounded-xl border px-3.5 py-3 text-[15px] leading-relaxed
                  ${TONE[tone]}`}
    >
      <Icon name={TONE_ICON[tone]} className="mt-0.5 size-5 shrink-0" />
      <span className="min-w-0">{children}</span>
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
  icon = "seedling",
  children,
}: {
  title?: string;
  action?: React.ReactNode;
  icon?: IconName;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-line bg-surface px-5 py-10 text-center shadow-soft">
      <span className="mx-auto mb-4 flex size-14 items-center justify-center rounded-2xl bg-brand-fill text-brand-strong">
        <Icon name={icon} className="size-7" />
      </span>
      {title && <p className="text-lg font-semibold text-ink">{title}</p>}
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
  eyebrow,
  className = "mb-6",
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  back?: { href: string; label: string };
  actions?: React.ReactNode;
  /** A small line above the title: a greeting, a date, a class. */
  eyebrow?: React.ReactNode;
  /** Spacing below; "mb-0" when the header sits inside another row. */
  className?: string;
}) {
  return (
    <header className={className}>
      {back && (
        <Link
          href={back.href}
          className="-ml-2 mb-2 inline-flex min-h-11 items-center gap-1 rounded-lg px-2
                     text-[15px] font-medium text-ink-muted hover:bg-sunken hover:text-ink"
        >
          <Icon name="chevronLeft" className="size-4" /> {back.label}
        </Link>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          {eyebrow && <p className="mb-1 text-sm font-medium text-ink-subtle">{eyebrow}</p>}
          <h1 className="text-[28px] font-bold leading-tight tracking-tight text-ink sm:text-[32px]">
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
    <div className={`rounded-2xl border border-line bg-surface shadow-soft ${className}`}>
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
    neutral: "bg-sunken text-ink-muted",
    ok: "bg-ok-fill text-ok",
    warn: "bg-warn-fill text-warn",
    risk: "bg-risk-fill text-risk",
  }[tone];
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs
                  font-semibold ${style}`}
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
        className="mt-1.5 block min-h-11 w-full rounded-xl border border-line-strong
                   bg-surface px-3.5 text-base text-ink focus:border-action focus:outline-none
                   focus:ring-4 focus:ring-brand-fill"
      >
        {children}
      </select>
      {hint && <span className="mt-1.5 block text-sm text-ink-subtle">{hint}</span>}
    </label>
  );
}

/** A rounded tile for an icon: navigation, actions, empty states. */
export function IconTile({
  name,
  tone = "brand",
  size = "md",
  className = "",
}: {
  name: IconName;
  tone?: "brand" | "accent" | "neutral";
  size?: "sm" | "md";
  className?: string;
}) {
  const style = {
    brand: "bg-brand-fill text-brand-strong",
    accent: "bg-accent-fill text-accent-strong",
    neutral: "bg-sunken text-ink-muted",
  }[tone];
  return (
    <span
      className={`flex shrink-0 items-center justify-center ${size === "sm" ? "size-8 rounded-lg" : "size-10 rounded-xl"} ${style} ${className}`}
    >
      <Icon name={name} className={size === "sm" ? "size-4" : "size-5"} />
    </span>
  );
}

/**
 * A two-to-four way switch: Current / Withdrawn, Most need first / A-Z.
 * Buttons with aria-pressed inside a labelled group, so a screen reader
 * hears which one is on.
 */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  className = "",
}: {
  label: string;
  value: T;
  options: { value: T; label: React.ReactNode }[];
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={`inline-flex rounded-xl bg-sunken p-1 ${className}`}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={`min-h-9 rounded-lg px-3.5 text-sm font-semibold transition-all
                      ${value === option.value ? "bg-surface text-ink shadow-soft" : "text-ink-muted hover:text-ink"}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

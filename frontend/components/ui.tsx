"use client";

/**
 * Small shared pieces, so pages read as what they do rather than as walls of
 * utility classes.
 */

export function Button({
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger";
}) {
  const styles = {
    primary: "bg-neutral-900 text-white hover:bg-neutral-800",
    secondary: "border border-neutral-300 bg-white hover:bg-neutral-100",
    danger: "border border-red-300 bg-white text-red-800 hover:bg-red-50",
  }[variant];

  return (
    <button
      {...props}
      className={`rounded px-3 py-1.5 text-sm font-medium disabled:opacity-50
                  ${styles} ${className}`}
    />
  );
}

export function Field({
  label,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="block text-sm">
      <span className="font-medium">{label}</span>
      <input
        {...props}
        className="mt-1 w-full rounded border border-neutral-300 px-3 py-1.5
                   text-sm focus:border-neutral-900 focus:outline-none"
      />
    </label>
  );
}

export function Note({
  tone = "info",
  children,
}: {
  tone?: "info" | "error";
  children: React.ReactNode;
}) {
  if (!children) return null;
  const styles =
    tone === "error"
      ? "border-red-200 bg-red-50 text-red-800"
      : "border-neutral-200 bg-neutral-50 text-neutral-700";
  return (
    <p
      role={tone === "error" ? "alert" : "status"}
      className={`rounded border px-3 py-2 text-sm ${styles}`}
    >
      {children}
    </p>
  );
}

export function Loading({ what }: { what: string }) {
  return <p className="text-sm text-neutral-500">Loading {what}…</p>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded border border-dashed border-neutral-300 px-4 py-8
                  text-center text-sm text-neutral-500">
      {children}
    </p>
  );
}

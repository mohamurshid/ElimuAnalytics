/**
 * The Elimu Analytics mark.
 *
 * An E built from the product's own vocabulary. The spine is a tier band, the
 * three arms step through the KICD ramp from Approaches at the foot to Exceeds
 * at the top, so the letter reads as a learner climbing a level. It draws with
 * the live tier tokens rather than fixed hex, which means it inverts in dark
 * mode exactly as the heatmap does - one ramp, one rule, everywhere.
 *
 * The static copies in app/icon.svg and public/elimu-logo.svg carry fixed
 * colours, because a favicon or a slide has no stylesheet to inherit from.
 */

export function Mark({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="4" y="4" width="5" height="20" rx="1.5" fill="var(--tier-below)" />
      <rect x="10.5" y="4" width="13.5" height="5" rx="1.5" fill="var(--tier-exceeds)" />
      <rect x="10.5" y="11.5" width="9.5" height="5" rx="1.5" fill="var(--tier-meets)" />
      <rect x="10.5" y="19" width="13.5" height="5" rx="1.5" fill="var(--tier-approaches)" />
    </svg>
  );
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Mark />
      <span className="text-[17px] leading-none tracking-tight">
        <span className="font-semibold text-ink">Elimu</span>
        {!compact && <span className="font-normal text-ink-muted"> Analytics</span>}
      </span>
      <span className="sr-only">Elimu Analytics</span>
    </span>
  );
}

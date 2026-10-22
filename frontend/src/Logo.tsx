import { useId } from "react";

/** The application's mark: two overlapping circles - the client's statements and IPRS's - and what they agree on. */
export function Logo({ className = "brand-mark" }: { className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <span className={className} aria-hidden>
      <svg viewBox="0 0 64 64" focusable="false">
        <defs>
          <linearGradient id={`${id}bg`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#4E9F3D" />
            <stop offset="0.55" stopColor="#1E5128" />
            <stop offset="1" stopColor="#191A19" />
          </linearGradient>
          <clipPath id={`${id}l`}><circle cx="25" cy="32" r="13" /></clipPath>
        </defs>
        <rect width="64" height="64" rx="15" fill={`url(#${id}bg)`} />
        <circle cx="39" cy="32" r="13" fill="#FFFFFF" clipPath={`url(#${id}l)`} />
        <circle cx="25" cy="32" r="13" fill="none" stroke="#FFFFFF" strokeWidth="4.5" />
        <circle cx="39" cy="32" r="13" fill="none" stroke="#D8E9A8" strokeWidth="4.5" />
      </svg>
    </span>
  );
}

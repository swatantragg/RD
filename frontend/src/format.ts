// Money is right-aligned #,##0.00; amounts arrive as exact decimal strings. Blank stays blank (never 0.00).
const money2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const int0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export type Num = number | string | null | undefined;
export const isBlank = (v: Num) => v === null || v === undefined || v === "";
export const num = (v: Num): number => (isBlank(v) ? 0 : Number(v));
export const money = (v: Num) => (isBlank(v) ? "" : money2.format(Number(v)));
export const int = (v: Num) => (isBlank(v) ? "" : int0.format(Number(v)));

export function compact(v: Num): string {
  if (isBlank(v)) return "";
  const n = Number(v);
  const a = Math.abs(n);
  if (a >= 1e7) return `${(n / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${(n / 1e5).toFixed(2)} L`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return money2.format(n);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function dmy(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}-${MONTHS[Number(m) - 1]}-${y}`;
}
export function mon(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m] = iso.slice(0, 7).split("-");
  return `${MONTHS[Number(m) - 1]} ${y}`;
}
export const period = (a?: string | null, b?: string | null) => (a && b ? `${mon(a)} – ${mon(b)}` : "period not stated");
export const when = (iso: string | null | undefined) => (iso ? iso.replace("T", " ").slice(0, 16) : "");
export function bytes(n: number): string {
  if (n > 1e6) return `${(n / 1e6).toFixed(2)} MB`;
  if (n > 1e3) return `${(n / 1e3).toFixed(1)} KB`;
  return `${n} B`;
}
export const words = (s: string | null | undefined) => (s ? s.replace(/_/g, " ").toLowerCase() : "");
export const today = () => new Date().toISOString().slice(0, 10);
export const plusDays = (n: number) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);

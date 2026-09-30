// Money is right-aligned #,##0.00 everywhere (architecture §18.1).
const money2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const int0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export const money = (v: number | null | undefined) => (v === null || v === undefined ? "" : money2.format(v));
export const int = (v: number | null | undefined) => (v === null || v === undefined ? "" : int0.format(v));

export function compact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return int0.format(v);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function dmy(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}-${MONTHS[Number(m) - 1]}-${y}`;
}
export function monthLabel(mk: string): string {
  const [y, m] = mk.split("-");
  return `${MONTHS[Number(m) - 1]} ${y}`;
}
export function fyLabel(k: string): string {
  if (k === "NA") return "Period Not Stated";
  const y = Number(k);
  return `FY ${y}-${String(y + 1).slice(-2)}`;
}
export function bytes(n: number): string {
  if (n > 1e6) return `${(n / 1e6).toFixed(2)} MB`;
  if (n > 1e3) return `${(n / 1e3).toFixed(1)} KB`;
  return `${n} B`;
}
export const ago = (iso: string) => iso?.replace("T", " ").slice(0, 16);

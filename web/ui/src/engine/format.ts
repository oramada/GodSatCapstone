// How numbers read on screen. A missing value is an en dash, never a guess.

export const MISSING = "–";

export function fixed(value: number | null | undefined, digits = 2, suffix = ""): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits }) + suffix
    : MISSING;
}

/** A model estimate as the model gives it: fixed digits, no grouping (the link readouts). */
export function plain(value: number | null | undefined, digits = 2, suffix = ""): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) + suffix : MISSING;
}

/** A comparison value: integers in full, others to 8 significant digits. */
export function figure(value: number | null): string {
  if (value === null) return MISSING;
  return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumSignificantDigits: 8 });
}

export function kilobytes(bytes: number): string {
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function shortDate(seconds: number): string {
  return new Date(seconds * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function sentence(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

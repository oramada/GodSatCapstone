import { describe, expect, it } from "vitest";

import { figure, fixed, kilobytes, MISSING, plain, sentence } from "./format";

describe("format", () => {
  it("never guesses a missing number", () => {
    expect(fixed(null)).toBe(MISSING);
    expect(fixed(undefined)).toBe(MISSING);
    expect(fixed(Number.NaN)).toBe(MISSING);
    expect(fixed(Number.POSITIVE_INFINITY)).toBe(MISSING);
    expect(figure(null)).toBe(MISSING);
  });

  it("fixes digits and adds the unit", () => {
    expect(fixed(1.5, 2, " km")).toBe((1.5).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " km");
    expect(fixed(0, 0)).toBe("0");
  });

  it("gives model estimates plain: fixed digits, no grouping, the unit after", () => {
    expect(plain(1234.5678, 3, " ms")).toBe("1234.568 ms");
    expect(plain(-0.5, 2, "°")).toBe("-0.50°");
    expect(plain(0, 2)).toBe("0.00");
    expect(plain(null)).toBe(MISSING);
    expect(plain(undefined)).toBe(MISSING);
    expect(plain(Number.NaN)).toBe(MISSING);
    expect(plain(Number.NEGATIVE_INFINITY, 2, " m")).toBe(MISSING);
  });

  it("keeps integers whole and others to 8 significant digits", () => {
    expect(figure(3)).toBe((3).toLocaleString());
    expect(figure(0.123456789)).toBe((0.12345679).toLocaleString(undefined, { maximumSignificantDigits: 8 }));
  });

  it("reads sizes in kilobytes", () => {
    expect(kilobytes(2048)).toBe("2.0 KB");
    expect(kilobytes(0)).toBe("0.0 KB");
  });

  it("capitalises the first letter only", () => {
    expect(sentence("observed now")).toBe("Observed now");
    expect(sentence("")).toBe("");
  });
});

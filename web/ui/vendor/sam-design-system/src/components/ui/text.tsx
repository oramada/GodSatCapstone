// Small print and readouts: a caption, a count, a time, a line of help that
// is not a Field's. New in the kit (not from Lanes): the type steps every
// screen already used by hand (`text-xs text-muted-foreground`,
// `text-sm tabular-nums`), named once so a screen never types a type class.
// Headings are SectionHeader and CardTitle; a label over a control is Field;
// a state is StatusLabel. `className` is for placement only.

import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentPropsWithRef } from "react";

import { cn } from "../../lib/utils";

export const textVariants = cva("", {
  variants: {
    /** The type step: `2xs` a footnote, `xs` small print, `sm` the body (default), `base` a lead line. */
    size: {
      "2xs": "text-2xs",
      xs: "text-xs",
      sm: "text-sm",
      base: "text-base",
    },
    /** `default` the foreground ink; `muted` the quiet ink for help and metadata. */
    tone: {
      default: "text-foreground",
      muted: "text-muted-foreground",
    },
    weight: {
      regular: "font-normal",
      medium: "font-medium",
      semibold: "font-semibold",
    },
    /** Tabular digits: a readout that changes must not shift what is beside it. */
    numeric: { true: "tabular-nums", false: "" },
    /** One line, cut short with … */
    truncate: { true: "truncate", false: "" },
    /** No lone last word on a wrapped line (`text-pretty`). */
    pretty: { true: "text-pretty", false: "" },
  },
  defaultVariants: { size: "sm", tone: "default", weight: "regular", numeric: false, truncate: false, pretty: false },
});

type TextVariants = VariantProps<typeof textVariants>;

export type TextProps = ComponentPropsWithRef<"p"> & {
  size?: NonNullable<TextVariants["size"]>;
  tone?: NonNullable<TextVariants["tone"]>;
  weight?: NonNullable<TextVariants["weight"]>;
  numeric?: boolean;
  truncate?: boolean;
  pretty?: boolean;
  /** The element: a paragraph by default; `span` inside a line, `div` around other blocks. */
  as?: "p" | "span" | "div";
};

export function Text({ size, tone, weight, numeric, truncate, pretty, as: Element = "p", className, ...props }: TextProps) {
  return (
    <Element
      data-slot="text"
      className={cn(textVariants({ size, tone, weight, numeric, truncate, pretty }), className)}
      {...(props as ComponentPropsWithRef<"div">)}
    />
  );
}

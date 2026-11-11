// Text a person reads as it is: JSON, a config, a log, the inputs behind a
// number. New in the kit, from the one place Lanes already drew it: the
// technical part of a problem (./problem.tsx `ProblemDetails`): the recessed
// fill, the inset radius, mono at the 2xs size, wrapped, in the muted ink.
// `copy` puts Copy beside it (the same button, with its pulse).
//
// `height`: how tall it may grow before it scrolls: `sm` (12rem, ProblemDetails'
// own), `md` (20rem), `none` (no limit).

import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "../../lib/utils";
import { CopyDetailsButton } from "./problem";

export const codeBlockVariants = cva(
  "w-full overflow-auto rounded-inset bg-fill px-2.5 py-2 font-mono text-2xs leading-relaxed whitespace-pre-wrap break-words text-muted-foreground",
  {
    variants: {
      height: {
        sm: "max-h-48",
        md: "max-h-80",
        none: "",
      },
    },
    defaultVariants: { height: "sm" },
  },
);

export type CodeBlockProps = Omit<ComponentProps<"pre">, "children"> &
  VariantProps<typeof codeBlockVariants> & {
    /** The text, shown exactly. */
    text: string;
    /** Copy beside it. */
    copy?: boolean;
    /** The block's spoken name ("Scene provenance"). */
    label?: string;
  };

export function CodeBlock({ text, copy = false, label, height, className, ...props }: CodeBlockProps) {
  return (
    <div data-slot="code-block" className={cn("flex min-w-0 flex-col items-start gap-1.5", className)}>
      <pre
        tabIndex={0}
        aria-label={label}
        className={cn(
          codeBlockVariants({ height }),
          "outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
        {...props}
      >
        {text}
      </pre>
      {copy ? <CopyDetailsButton text={text} /> : null}
    </div>
  );
}

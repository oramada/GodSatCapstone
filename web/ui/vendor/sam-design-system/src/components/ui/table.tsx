// A data table: rows of the same fields, read across. New in the kit (Lanes
// shows people in a table it composes on the page, with SortButton for its
// headings); this gives every project the same table so none hand-rolls one.
// The look is the settings group's (./list.tsx `ListGroup`): a quiet bordered
// box at the row radius, hairlines between rows (`border-border/50`), the
// heading in the small muted ink, numbers in tabular figures. The box scrolls
// on both axes, so a wide table never pushes its page sideways on a phone, and
// its heading row stays at the top while the body scrolls under it.
//
// `size`: `default` (py-2), `compact` (py-1.5, a dense readout). `height`:
// how tall the box may grow before it scrolls: `auto` (no limit), `sm`
// (14rem), `md` (20rem), `lg` (28rem).

import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "../../lib/utils";

export const tableVariants = cva(
  "relative w-full overflow-auto rounded-row border border-border/60 bg-card/40 shadow-xs/5 [scrollbar-gutter:stable]",
  {
    variants: {
      height: {
        auto: "",
        sm: "max-h-56",
        md: "max-h-80",
        lg: "max-h-112",
      },
      size: {
        default: "[--table-cell-y:--spacing(2)]",
        compact: "[--table-cell-y:--spacing(1.5)]",
      },
    },
    defaultVariants: { height: "auto", size: "default" },
  },
);

export type TableProps = ComponentProps<"table"> &
  VariantProps<typeof tableVariants> & {
    /** The table's spoken name, when no caption says it. */
    label?: string;
    /** Busy while its rows are being read. */
    busy?: boolean;
  };

export function Table({ height, size, label, busy, className, children, ...props }: TableProps) {
  return (
    <div data-slot="table" className={cn(tableVariants({ height, size }), className)} aria-busy={busy || undefined}>
      <table aria-label={label} className="w-full border-collapse text-left text-xs" {...props}>
        {children}
      </table>
    </div>
  );
}

export function TableHeader({ className, ...props }: ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("sticky top-0 z-10 bg-popover/95 backdrop-blur-sm [&_tr]:border-b [&_tr]:border-border/60", className)}
      {...props}
    />
  );
}

export function TableBody({ className, ...props }: ComponentProps<"tbody">) {
  return <tbody data-slot="table-body" className={cn("[&>tr+tr]:border-t [&>tr+tr]:border-border/50", className)} {...props} />;
}

export function TableRow({ className, ...props }: ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn("transition-colors duration-(--motion-fast) hover:bg-fill-hover/40 motion-reduce:transition-none", className)}
      {...props}
    />
  );
}

export function TableHead({
  numeric = false,
  className,
  ...props
}: ComponentProps<"th"> & {
  /** Heads a numeric column: set to the end, over its digits. */
  numeric?: boolean;
}) {
  return (
    <th
      data-slot="table-head"
      scope="col"
      className={cn(
        "px-3 py-(--table-cell-y) align-bottom font-medium whitespace-nowrap text-muted-foreground",
        numeric && "text-right",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({
  numeric = false,
  tabular = false,
  code = false,
  className,
  ...props
}: ComponentProps<"td"> & {
  /** A number: tabular figures, set to the end so the digits line up. */
  numeric?: boolean;
  /** A time or an identifier read as figures: tabular, on one line, at the start. */
  tabular?: boolean;
  /** A key, a path or a field name: monospace, breaking anywhere rather than widening the table. */
  code?: boolean;
}) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "px-3 py-(--table-cell-y) align-top text-foreground",
        numeric && "text-right tabular-nums whitespace-nowrap",
        tabular && "tabular-nums whitespace-nowrap",
        code && "font-mono text-xs break-all",
        className,
      )}
      {...props}
    />
  );
}

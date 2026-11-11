// A titled block that opens and closes in place: a heading you press, a
// chevron that turns, the body revealed under it. New in the kit, from two
// pieces it already had: ProblemDetails' trigger (./problem.tsx: a quiet
// press with a ChevronRight that turns a quarter as it opens) at the size of
// a SectionHeader's section title (./section-header.tsx), over
// CollapsiblePanel's reveal (./collapsible.tsx: height and a clip, on
// --motion-reveal, still under reduced motion).
//
// `variant`: `section` (a block of a panel: the section title's size, a line
// of description under it, a rule above the next one when stacked in
// `DisclosureGroup`) or `quiet` (ProblemDetails' small muted press, for
// something technical inside a block: a provenance, a model's inputs).

import { ChevronRightIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/utils";
import { Button } from "./button";
import { Collapsible, CollapsiblePanel, CollapsibleTrigger } from "./collapsible";

export type DisclosureProps = {
  title: ReactNode;
  /** A lucide icon before the title (new in the kit), in the quiet ink. */
  icon?: ReactNode;
  /** One line under the title (`section` only). */
  description?: ReactNode;
  /** On the right of a `section`'s title: a count, a badge. */
  meta?: ReactNode;
  variant?: "section" | "quiet";
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: ReactNode;
  className?: string;
};

export function Disclosure({
  title,
  icon,
  description,
  meta,
  variant = "section",
  defaultOpen,
  open,
  onOpenChange,
  children,
  className,
}: DisclosureProps) {
  const quiet = variant === "quiet";
  const chevron = (
    <ChevronRightIcon
      aria-hidden
      className="shrink-0 transition-transform duration-(--motion-base) group-data-panel-open:rotate-90 motion-reduce:transition-none"
    />
  );
  return (
    <Collapsible
      data-slot="disclosure"
      data-variant={variant}
      className={cn("min-w-0", className)}
      {...(defaultOpen !== undefined ? { defaultOpen } : {})}
      {...(open !== undefined ? { open } : {})}
      {...(onOpenChange ? { onOpenChange: (next: boolean) => onOpenChange(next) } : {})}
    >
      {quiet ? (
        <CollapsibleTrigger render={<Button size="xs" variant="ghost-muted" className="group -ms-1.5" />}>
          {chevron}
          {icon}
          {title}
        </CollapsibleTrigger>
      ) : (
        <CollapsibleTrigger
          render={
            <Button
              variant="ghost"
              size="sm-multiline"
              className="group h-auto w-full justify-start gap-2 rounded-row px-2 py-2 text-left"
            />
          }
        >
          <span className="text-muted-foreground">{chevron}</span>
          {icon ? (
            <span aria-hidden className="flex shrink-0 text-muted-foreground [&_svg]:size-4">
              {icon}
            </span>
          ) : null}
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-sm font-semibold text-foreground">{title}</span>
            {description ? <span className="text-xs font-normal text-muted-foreground">{description}</span> : null}
          </span>
          {meta ? <span className="shrink-0 text-xs font-normal text-muted-foreground tabular-nums">{meta}</span> : null}
        </CollapsibleTrigger>
      )}
      <CollapsiblePanel>
        <div className={cn(quiet ? "mt-1" : "px-2 pt-2 pb-3")}>{children}</div>
      </CollapsiblePanel>
    </Collapsible>
  );
}

/** Disclosures stacked in one column, a hairline between each. */
export function DisclosureGroup({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div data-slot="disclosure-group" className={cn("flex flex-col [&>*+*]:border-t [&>*+*]:border-border/50", className)}>
      {children}
    </div>
  );
}

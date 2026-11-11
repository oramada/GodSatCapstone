// The heading over a block of a screen. From pingdotgg/t3code
// apps/web/src/components/settings/settingsLayout.tsx (MIT, Copyright (c) T3
// Tools Inc.; full notice in app/ui/THIRD_PARTY_NOTICES.md), its
// SettingsSection header: a title (with an icon) on the left at the rows'
// inset, an action on the right. Changes: a description under the title (as
// Connections and Settings both added it), and three levels, each a heading
// Lanes already drew by hand:
//
//   page     Settings' section head (screens/settings/SettingsScreen.tsx): the
//            section's name, large, and what it is for
//   section  t3code's settings section header (the default)
//   eyebrow  the small capitals over a drawer's block ("About them", LeadDrawer.tsx)
//   step     a question inside a step's panel (About you): a small icon, the
//            words in the reading size at 500, and a hint after them in the
//            muted ink ("Pick any"); never inset
//   panel    the title of a floating tool panel (new in the kit): large and
//            tight, a small description under it, the action on the right;
//            not inset (the panel's header has its own room)
//
// `icon` (every level) sits before the title words, sized to them and in the
// quiet ink: 20px on a panel, 16px on a section, 14px on an eyebrow.
//
// `eyebrow` (section and panel) is the small capitals over the title, inside
// its column: what the title belongs to. It is a paragraph, not a heading.
// `headingProps` reach the heading itself, at every level: a `ref` and
// `tabIndex={-1}` to move focus to it, an `id` for `aria-labelledby`.

import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentPropsWithoutRef, ComponentPropsWithRef, ReactNode } from "react";

import { cn } from "../../lib/utils";

const headerVariants = cva("", {
  variants: {
    level: {
      page: "space-y-1",
      section: "flex min-h-7 items-start justify-between gap-4",
      eyebrow: "flex items-center justify-between gap-3",
      step: "flex flex-wrap items-center gap-x-2 gap-y-0.5",
      panel: "flex min-h-7 items-start justify-between gap-3",
    },
    /** Inset to line up with the rows of a ListGroup under it (t3code's px-3 sm:px-4). */
    inset: {
      true: "px-3 sm:px-4",
      false: "",
    },
  },
  defaultVariants: { level: "section", inset: true },
});

const TITLE = {
  page: "text-xl font-semibold tracking-tight text-foreground",
  section:
    "flex min-h-7 items-center gap-2 text-base font-semibold text-foreground [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground",
  eyebrow:
    "flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase [&_svg]:size-3.5 [&_svg]:shrink-0",
  step: "flex items-center gap-2 text-reading leading-6 font-medium tracking-tight text-foreground [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground",
  panel:
    "text-lg font-semibold tracking-tight text-foreground [&_svg]:size-5 [&_svg]:shrink-0 [&_svg]:text-muted-foreground",
} as const;

/** The small capitals over a section's or a panel's title. */
const EYEBROW = "text-xs font-medium tracking-wide text-muted-foreground uppercase";

const DESCRIPTION = {
  page: "text-sm text-muted-foreground",
  section: "max-w-2xl text-xs text-muted-foreground",
  eyebrow: "text-xs text-muted-foreground",
  step: "text-body leading-6 text-muted-foreground",
  panel: "text-xs text-muted-foreground",
} as const;

export type SectionHeaderProps = Omit<ComponentPropsWithoutRef<"header">, "title"> &
  VariantProps<typeof headerVariants> & {
    title: ReactNode;
    description?: ReactNode;
    /** Before the title: a logo, a lucide icon. */
    icon?: ReactNode;
    /** On the right: a button, a status line. */
    action?: ReactNode;
    /** The heading element; `h2` by default, `h3` inside a section. */
    as?: "h1" | "h2" | "h3";
    /** Small capitals over the title, in its column (levels `section` and `panel`; ignored by the others). Not a heading. */
    eyebrow?: ReactNode;
    /** Spread on the heading element, at every level: `ref`, `id`, `tabIndex`, `className` (`outline-none` for a focus target). */
    headingProps?: ComponentPropsWithRef<"h2">;
  };

export function SectionHeader({
  title,
  description,
  icon,
  action,
  level,
  inset,
  as: Heading = "h2",
  eyebrow,
  headingProps,
  className,
  ...props
}: SectionHeaderProps) {
  const at = level ?? "section";
  const resolvedInset = inset ?? (at !== "eyebrow" && at !== "step" && at !== "panel");
  const heading = (look: string) => ({ ...headingProps, className: cn(look, headingProps?.className) });
  if (at === "step") {
    return (
      <header
        data-slot="section-header"
        data-level={at}
        className={cn(headerVariants({ level: at, inset: resolvedInset }), className)}
        {...props}
      >
        <Heading {...heading(TITLE.step)}>
          {icon}
          {title}
        </Heading>
        {description ? <p className={DESCRIPTION.step}>{description}</p> : null}
      </header>
    );
  }
  if (at === "page") {
    return (
      <header
        data-slot="section-header"
        data-level={at}
        className={cn(headerVariants({ level: at, inset: resolvedInset }), className)}
        {...props}
      >
        <Heading {...heading(TITLE.page)}>{title}</Heading>
        {description ? <p className={DESCRIPTION.page}>{description}</p> : null}
      </header>
    );
  }
  return (
    <header
      data-slot="section-header"
      data-level={at}
      className={cn(headerVariants({ level: at, inset: resolvedInset }), className)}
      {...props}
    >
      <div className={cn("min-w-0", (at === "section" || at === "panel") && "space-y-0.5")}>
        {eyebrow && at !== "eyebrow" ? <p className={EYEBROW}>{eyebrow}</p> : null}
        <Heading {...heading(cn(TITLE[at], at === "panel" && icon && "flex items-center gap-2"))}>
          {icon}
          {title}
        </Heading>
        {description ? <p className={DESCRIPTION[at]}>{description}</p> : null}
      </div>
      {at === "section" || (at === "panel" && action) ? (
        <div className="flex min-h-7 min-w-7 shrink-0 items-center justify-end gap-1">{action}</div>
      ) : action ? (
        <div className="flex shrink-0 items-center gap-1">{action}</div>
      ) : null}
    </header>
  );
}

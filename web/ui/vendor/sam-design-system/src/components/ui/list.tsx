// Rows in a rounded group, under a heading: the layout of every settings-like
// screen. From pingdotgg/t3code apps/web/src/components/settings/settingsLayout.tsx
// and SettingsGroup.tsx (MIT, Copyright (c) T3 Tools Inc.; full notice in
// app/ui/THIRD_PARTY_NOTICES.md): SettingsGroup, SettingsRow and
// SettingsSection, without t3code's settings scopes, inheritance markers,
// managed-policy locks and search targets (Lanes has one owner and one
// kernel). Lanes had two copies of these (components/connections/
// SettingsLayout.tsx and screens/settings/layout.tsx); this is the one.
// Changes:
//   * ListRow takes a `media` slot (a logo, an avatar) before its title.
//   * ListRow's `variant`: `setting` is t3code's row (a title that wraps, the
//     status under it as a block); `item` is a row about a thing (an account,
//     a service): the title on one line, the status a line of dot, word and
//     badges, the controls free to wrap, and colour that eases.
//   * `hover`: opencode's overlay hover, for rows you can act on.
//   * `titleAs`: the title's element (h3 by default; h4, p or span).
//   * Selectable rows (new in the kit): with `onSelect`, the row is one
//     `<button>`, hover-filled, the chosen one drawn as its fill (`bg-accent`,
//     patterns.md: never a side bar) and read as `aria-current`. A button holds
//     no heading, control or block, so its title is a span and the types
//     refuse `control` and `children`.
//   * ListSection's header is ./section-header.tsx (with a description).

import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps, ComponentPropsWithoutRef, ReactNode } from "react";

import { cn } from "../../lib/utils";
import { SectionHeader } from "./section-header";

export const listGroupVariants = cva("relative overflow-visible text-foreground", {
  variants: {
    variant: {
      /** t3code's settings group: a quiet bordered box. */
      grouped: "rounded-xl border border-border/60 bg-card/40 shadow-xs/5",
      /** No box: rows stand on the page. */
      plain: "space-y-1",
    },
    /** Hairlines between the rows (grouped only). */
    divided: { true: "", false: "" },
  },
  compoundVariants: [
    {
      variant: "grouped",
      divided: true,
      className: "[&>*+*]:border-t [&>*+*]:border-border/50 [&>[data-slot=settings-row]]:rounded-none",
    },
  ],
  defaultVariants: { variant: "grouped", divided: true },
});

export function ListGroup({
  variant,
  divided,
  className,
  ...props
}: ComponentProps<"div"> & VariantProps<typeof listGroupVariants>) {
  return <div data-slot="settings-group" {...props} className={cn(listGroupVariants({ variant, divided }), className)} />;
}

export const listRowVariants = cva(
  "group/settings-row @container/settings-row rounded-xl px-3 sm:px-4 aria-disabled:opacity-64 aria-disabled:[&_*]:text-muted-foreground",
  {
    variants: {
      variant: {
        setting: "",
        item: "transition-colors duration-(--motion-fast)",
      },
      /** opencode's overlay hover, for a row you can act on. */
      hover: {
        true: "hover:bg-fill-hover/40",
        false: "",
      },
    },
    defaultVariants: { variant: "setting", hover: false },
  },
);

type ListRowCommon = VariantProps<typeof listRowVariants> & {
  title: ReactNode;
  description?: ReactNode;
  /** A line under the description: a state, a save's result, a failure. */
  status?: ReactNode;
  /** Before the title: a logo, an avatar. */
  media?: ReactNode;
  /**
   * The control stays beside the title at every width. Left out, a row narrower than 32rem
   * puts its control under the title (a settings page on a phone); `inline` is for a narrow
   * panel's switches and small selects, where stacking doubles every row's height.
   */
  inline?: boolean;
};

/** A row that holds things: a title (a heading by default), a control, a block under it. */
export type ListRowStaticProps = Omit<ComponentPropsWithoutRef<"div">, "title" | "onSelect"> &
  ListRowCommon & {
    /** The title's element: `h3` (default) under a section's `h2`; `h4` a level deeper; `p` or `span` where rows are not headings (a long list of things). */
    titleAs?: "h3" | "h4" | "p" | "span";
    /** On the right: a switch, a button, a select. */
    control?: ReactNode;
    /** Under the row, inside it: a list, a form. */
    children?: ReactNode;
    onSelect?: undefined;
    selected?: undefined;
  };

/**
 * A row that is one press: picking it chooses the thing (a file in a list, an object to inspect).
 * The whole row is a `<button>`; it cannot hold a heading, a control or a block under it.
 */
export type ListRowSelectableProps = Omit<ComponentPropsWithoutRef<"button">, "title" | "onSelect" | "onClick" | "type" | "children"> &
  ListRowCommon & {
    /** Called when the row is pressed (pointer, Enter, Space). */
    onSelect: () => void;
    /** The chosen row: drawn as its fill (`bg-accent`, never a side bar) and read as `aria-current`. */
    selected?: boolean;
    titleAs?: never;
    control?: never;
    children?: never;
  };

export type ListRowProps = ListRowStaticProps | ListRowSelectableProps;

/** The media slot: a logo or an avatar as it is; a bare lucide icon at the title's size, in the quiet ink. */
const MEDIA = "flex shrink-0 items-center pt-0.5 [&>svg]:size-4 [&>svg]:text-muted-foreground";

/** The kit's focus ring (Button's). */
const FOCUS_RING =
  "outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background";

export function ListRow(props: ListRowProps) {
  if (props.onSelect) {
    const { title, description, status, media, variant, hover: _hover, inline: _inline, onSelect, selected = false, className, ...buttonProps } =
      props;
    const item = variant === "item";
    return (
      <button
        type="button"
        {...buttonProps}
        data-slot="settings-row"
        aria-current={selected ? "true" : undefined}
        onClick={() => onSelect()}
        className={cn(
          listRowVariants({ variant, hover: !selected }),
          "block w-full cursor-pointer py-3 text-start transition-colors duration-(--motion-fast) disabled:pointer-events-none disabled:opacity-64",
          selected && "bg-accent",
          FOCUS_RING,
          className,
        )}
      >
        <span className="flex min-w-0 items-start gap-3">
          {media ? <span className={MEDIA}>{media}</span> : null}
          <span className="block min-w-0 flex-1 space-y-1">
            <span
              className={cn(
                "flex min-h-5 min-w-0 items-center text-sm font-medium text-foreground",
                item && "gap-1.5",
              )}
            >
              <span className={cn("min-w-0", item && "truncate")}>{title}</span>
            </span>
            {description ? (
              <span className="block max-w-2xl text-balance text-xs leading-normal text-muted-foreground">{description}</span>
            ) : null}
            {status ? (
              <span className={cn("block pt-0.5 text-xs text-muted-foreground", item && "flex flex-wrap items-center gap-1.5")}>
                {status}
              </span>
            ) : null}
          </span>
        </span>
      </button>
    );
  }
  const {
    title,
    description,
    status,
    media,
    control,
    children,
    variant,
    hover,
    inline = false,
    titleAs: Title = "h3",
    onSelect: _onSelect,
    selected: _selected,
    className,
    ...rowProps
  } = props;
  const item = variant === "item";
  return (
    <div
      {...rowProps}
      data-slot="settings-row"
      className={cn(listRowVariants({ variant, hover }), children ? "pt-3 pb-3" : "py-3", className)}
    >
      <div
        data-inline={inline || undefined}
        className={cn(
          inline
            ? "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4"
            : "flex flex-col gap-3 @min-[32rem]/settings-row:grid @min-[32rem]/settings-row:grid-cols-[minmax(0,1fr)_minmax(10rem,auto)] @min-[32rem]/settings-row:items-center @min-[32rem]/settings-row:gap-8",
        )}
      >
        <div className="flex min-w-0 flex-1 items-start gap-3">
          {media ? <div className={MEDIA}>{media}</div> : null}
          <div className="min-w-0 flex-1 space-y-1">
            {item ? (
              <div className="flex min-h-5 min-w-0 items-center gap-1.5">
                <Title className="min-w-0 truncate text-sm font-medium text-foreground">{title}</Title>
              </div>
            ) : (
              <Title className="flex min-h-5 items-center text-sm font-medium text-foreground">{title}</Title>
            )}
            {description ? (
              <p className="max-w-2xl text-balance text-xs leading-normal text-muted-foreground">{description}</p>
            ) : null}
            {status ? (
              <div
                className={cn(
                  "pt-0.5 text-xs text-muted-foreground",
                  item && "flex flex-wrap items-center gap-1.5",
                )}
              >
                {status}
              </div>
            ) : null}
          </div>
        </div>
        {control ? (
          <div
            className={cn(
              "flex min-w-0 shrink-0 items-center gap-2",
              inline ? "justify-end" : "w-full @min-[32rem]/settings-row:w-auto @min-[32rem]/settings-row:justify-end",
              item && "flex-wrap",
            )}
          >
            {control}
          </div>
        ) : null}
      </div>
      {children}
    </div>
  );
}

export type ListSectionProps = Omit<ComponentPropsWithoutRef<"section">, "title"> & {
  title: ReactNode;
  /** One line under the title. */
  description?: ReactNode;
  icon?: ReactNode;
  /** On the right of the title: an add button, a save's status line. */
  headerAction?: ReactNode;
  variant?: VariantProps<typeof listGroupVariants>["variant"];
  children: ReactNode;
};

/** A heading and its group of rows (t3code's SettingsSection). */
export function ListSection({
  title,
  description,
  icon,
  headerAction,
  variant,
  children,
  className,
  ...sectionProps
}: ListSectionProps) {
  return (
    <section data-slot="settings-section" {...sectionProps} className={cn("space-y-2.5", className)}>
      <SectionHeader as="h2" title={title} description={description} icon={icon} action={headerAction} />
      <ListGroup variant={variant}>{children}</ListGroup>
    </section>
  );
}

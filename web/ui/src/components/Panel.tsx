// A tool panel floating over the globe: glass, a title with Close, its body scrolling inside.
// Panels stay mounted while closed (Presence: `hidden` once its exit has run): the detail
// view's canvas, a running screening and a half-filled form keep their state. A panel grows
// from the toolbar button that opened it and shrinks back to it (rules 10 to 12). On a phone
// it fills the space under the toolbar; from `sm` it stands at its side of the window.

import { GlassPanel, GlassPanelBody, GlassPanelHeader, IconButton, Presence, SectionHeader, Text, type TextProps } from "@sam/design-system";
import { type LucideIcon, XIcon } from "lucide-react";
import type { ReactNode, RefObject } from "react";

import { cn } from "@sam/design-system/utils";

export type PanelId = "experiment" | "layers" | "data" | "inspect";

const PLACE: Record<"left" | "right" | "wide", string> = {
  left: "sm:right-auto sm:w-96",
  right: "sm:left-auto sm:w-96",
  wide: "sm:left-auto sm:w-full sm:max-w-3xl",
};

export function Panel({
  id,
  title,
  icon: Icon,
  eyebrow,
  label,
  closeLabel,
  open,
  side,
  onClose,
  headingRef,
  trigger,
  children,
}: {
  id: string;
  title: string;
  /** The panel's mark: the same one its toolbar button wears. */
  icon: LucideIcon;
  /** What the panel belongs to, in small capitals over its title. */
  eyebrow?: string;
  /** The region's spoken name. */
  label: string;
  /** What its Close button says to a screen reader: "Close layers panel". */
  closeLabel: string;
  open: boolean;
  side: keyof typeof PLACE;
  onClose: () => void;
  headingRef: (node: HTMLHeadingElement | null) => void;
  /** The toolbar button that opens it: where it grows from and goes back to. */
  trigger: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  return (
    <Presence
      as="section"
      open={open}
      trigger={trigger}
      id={id}
      role="region"
      aria-label={label}
      className={cn("fixed inset-x-2 top-29 bottom-2 z-30 flex sm:inset-x-4 sm:top-20 sm:bottom-4", PLACE[side])}
    >
      <GlassPanel padding="none" className="flex min-h-0 w-full flex-col">
        <GlassPanelHeader>
          <SectionHeader
            level="panel"
            icon={<Icon aria-hidden />}
            title={title}
            eyebrow={eyebrow}
            headingProps={{ ref: headingRef, tabIndex: -1, className: "outline-none" }}
            className="min-w-0 flex-1"
          />
          <IconButton label={closeLabel} shortcut="escape" onClick={onClose} tooltipSide="left">
            <XIcon />
          </IconButton>
        </GlassPanelHeader>
        <GlassPanelBody>{children}</GlassPanelBody>
      </GlassPanel>
    </Presence>
  );
}

/** A small line of explanation: scope, limits, units. The kit's small print, quiet and unwidowed. */
export function Fine(props: Omit<TextProps, "size" | "tone" | "pretty">) {
  return <Text size="xs" tone="muted" pretty {...props} />;
}

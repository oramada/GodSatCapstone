// Copied from pingdotgg/t3code apps/web/src/components/ui/sheet.tsx (https://github.com/pingdotgg/t3code).
// MIT License, Copyright (c) T3 Tools Inc. Full notice in app/ui/THIRD_PARTY_NOTICES.md.


import { Dialog as SheetPrimitive } from "@base-ui/react/dialog";
import { XIcon } from "lucide-react";
import { cn } from "../../lib/utils";
import { Button } from "./button";
import { ControlledOpenContext, renderRetainedPopup } from "./dialog";

function Sheet<Payload>(props: SheetPrimitive.Root.Props<Payload>) {
  return (
    <ControlledOpenContext value={props.open}>
      <SheetPrimitive.Root {...props} />
    </ControlledOpenContext>
  );
}

const SheetPortal = SheetPrimitive.Portal;

function SheetBackdrop({ className, ...props }: SheetPrimitive.Backdrop.Props) {
  return (
    <SheetPrimitive.Backdrop
      className={cn(
        "motion-backdrop fixed inset-0 z-(--z-sheet) bg-background/60 backdrop-blur-xs",
        className,
      )}
      data-slot="sheet-backdrop"
      {...props}
    />
  );
}

function SheetViewport({
  className,
  side,
  variant = "default",
  ...props
}: SheetPrimitive.Viewport.Props & {
  side?: "right" | "left" | "top" | "bottom";
  variant?: "default" | "inset";
}) {
  return (
    <SheetPrimitive.Viewport
      className={cn(
        "fixed inset-0 z-(--z-sheet) grid",
        side === "bottom" && "grid grid-rows-[1fr_auto] pt-12",
        side === "top" && "grid grid-rows-[auto_1fr] pb-12",
        side === "left" && "flex justify-start",
        side === "right" && "flex justify-end",
        variant === "inset" && "sm:p-4",
        className,
      )}
      data-slot="sheet-viewport"
      {...props}
    />
  );
}

function SheetPopup({
  className,
  children,
  showCloseButton = true,
  keepMounted = false,
  transitionDurationMs,
  side = "right",
  variant = "default",
  style,
  ...props
}: SheetPrimitive.Popup.Props & {
  showCloseButton?: boolean;
  keepMounted?: boolean;
  transitionDurationMs?: number;
  side?: "right" | "left" | "top" | "bottom";
  variant?: "default" | "inset";
}) {
  // Its durations are the motion tokens (--motion-sheet, 20% less out); 0 alone is honoured: no motion.
  const instant = transitionDurationMs === 0;

  return (
    <SheetPortal keepMounted={keepMounted}>
      <SheetBackdrop
        className={
          instant
            ? "transition-none! data-ending-style:opacity-100! data-starting-style:opacity-100!"
            : undefined
        }
      />
      <SheetViewport side={side} variant={variant}>
        <SheetPrimitive.Popup
          className={cn(
            "relative flex max-h-full min-h-0 w-full min-w-0 flex-col bg-popover not-dark:bg-clip-padding text-popover-foreground shadow-lg/5 motion-sheet will-change-transform before:pointer-events-none before:absolute before:inset-0 before:shadow-[0_1px_--theme(--color-black/4%)] max-sm:before:hidden dark:before:shadow-[0_-1px_--theme(--color-white/6%)]",
            side === "bottom" &&
              "row-start-2 border-t [--sheet-from:0_calc(var(--sheet-distance)*var(--motion-travel))]",
            side === "top" &&
              "border-b [--sheet-from:0_calc(var(--sheet-distance)*var(--motion-travel)*-1)]",
            side === "left" &&
              "w-[calc(100%-(--spacing(12)))] max-w-md border-e [--sheet-from:calc(var(--sheet-distance)*var(--motion-travel)*-1)_0]",
            side === "right" &&
              "col-start-2 w-[calc(100%-(--spacing(12)))] max-w-md border-s [--sheet-from:calc(var(--sheet-distance)*var(--motion-travel))_0]",
            variant === "inset" &&
              "before:hidden sm:rounded-2xl sm:border sm:before:rounded-[calc(var(--radius-2xl)-1px)] sm:**:data-[slot=sheet-footer]:rounded-b-[calc(var(--radius-2xl)-1px)]",
            instant &&
              "transition-none! will-change-auto! data-ending-style:translate-x-0! data-starting-style:translate-x-0! data-ending-style:translate-y-0! data-starting-style:translate-y-0! data-ending-style:opacity-100! data-starting-style:opacity-100!",
            className,
          )}
          data-slot="sheet-popup"
          render={keepMounted ? undefined : renderRetainedPopup}
          style={style}
          {...props}
        >
          {children}
          {showCloseButton && (
            <SheetPrimitive.Close
              aria-label="Close"
              className="absolute end-2 top-2"
              render={<Button size="icon" variant="ghost" />}
            >
              <XIcon />
            </SheetPrimitive.Close>
          )}
        </SheetPrimitive.Popup>
      </SheetViewport>
    </SheetPortal>
  );
}

function SheetHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "flex flex-col gap-2 p-6 in-[[data-slot=sheet-popup]:has([data-slot=sheet-panel])]:pb-3 max-sm:pb-4",
        className,
      )}
      data-slot="sheet-header"
      {...props}
    />
  );
}

function SheetTitle({ className, ...props }: SheetPrimitive.Title.Props) {
  return (
    <SheetPrimitive.Title
      className={cn("font-semibold text-xl leading-none", className)}
      data-slot="sheet-title"
      {...props}
    />
  );
}

function SheetDescription({ className, ...props }: SheetPrimitive.Description.Props) {
  return (
    <SheetPrimitive.Description
      className={cn("text-muted-foreground text-sm", className)}
      data-slot="sheet-description"
      {...props}
    />
  );
}

export {
  Sheet,
  SheetPortal,
  SheetBackdrop,
  SheetBackdrop as SheetOverlay,
  SheetPopup,
  SheetPopup as SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
};

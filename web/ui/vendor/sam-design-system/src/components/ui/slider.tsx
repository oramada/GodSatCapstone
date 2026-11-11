// A value picked by dragging along a track: a timeline's scrubber, a level.
// New in the kit (not from Lanes), on Base UI's Slider
// (@base-ui/react/slider), drawn with the kit's own parts: the track is the
// recessed fill a ProgressMeter runs on (`bg-fill`), the filled share is the
// lit rung (`bg-primary`), and the thumb is Switch's knob (`bg-background`,
// raised) so the two read as one family. `marks` lays a row of states under
// the track, one equal segment per step, each in a StatusDot tone: a
// timeline's observed, stale and lost steps, read at a glance. `largeStep` is
// what Shift+arrow and Page Up/Page Down move by.
//
// Motion (design/motion/README.md): the thumb grows a little while it is held
// (rule 4's press, on the knob), on --motion-press, and stays still under
// reduced motion. The fill follows the value at once: a scrubber that lags
// behind a playing timeline reads as a stall.

import { Slider as SliderPrimitive } from "@base-ui/react/slider";
import type { ReactNode } from "react";

import type { StatusTone } from "../../design/morrow/StatusDot";
import { cn } from "../../lib/utils";

const MARK: Record<StatusTone, string> = {
  neutral: "bg-muted-foreground/50",
  live: "bg-soft-sky",
  attention: "bg-warning",
  success: "bg-success",
  danger: "bg-destructive",
  info: "bg-info",
  idle: "bg-fill",
};

export interface SliderMark {
  tone: StatusTone;
  /** Said on hover: the step and its state. */
  title?: string;
}

export type SliderProps = {
  /** The spoken name of the thumb. */
  label: string;
  value: number;
  min?: number;
  max: number;
  step?: number;
  /** How far Shift+arrow and Page Up/Page Down move (Base UI's default: 10). A timeline's minute, a level's tenth. */
  largeStep?: number;
  onChange: (value: number) => void;
  /** Called once the person lets go (a drag's end, a key press). */
  onCommit?: (value: number) => void;
  /** Spoken value: "02:30 of 12:00" rather than "150". */
  valueText?: (value: number) => string;
  /** One state per step under the track (a timeline's custody). Left out, the track stands alone. */
  marks?: readonly SliderMark[];
  /** What is under the marks: words at either end ("Start", "12 minutes"). */
  ends?: [ReactNode, ReactNode];
  disabled?: boolean;
  className?: string;
};

export function Slider({
  label,
  value,
  min = 0,
  max,
  step = 1,
  largeStep,
  onChange,
  onCommit,
  valueText,
  marks,
  ends,
  disabled = false,
  className,
}: SliderProps) {
  return (
    <div data-slot="slider" className={cn("flex w-full min-w-0 flex-col gap-1.5", className)}>
      <SliderPrimitive.Root
        value={value}
        min={min}
        max={Math.max(min, max)}
        step={step}
        {...(largeStep === undefined ? {} : { largeStep })}
        disabled={disabled}
        onValueChange={(next) => onChange(next)}
        onValueCommitted={(next) => onCommit?.(next)}
        className="w-full touch-none select-none data-disabled:opacity-64"
      >
        <SliderPrimitive.Control className="relative flex h-5 w-full cursor-pointer items-center data-disabled:cursor-not-allowed">
          <SliderPrimitive.Track className="relative h-1.5 w-full rounded-capsule bg-fill">
            <SliderPrimitive.Indicator className="rounded-capsule bg-primary" />
            <SliderPrimitive.Thumb
              getAriaLabel={() => label}
              getAriaValueText={valueText ? (_formatted, current) => valueText(current) : undefined}
              className="block size-4 rounded-full bg-background shadow-raised outline-none transition-[scale] duration-(--motion-press) ease-out focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background data-dragging:scale-110 motion-reduce:transition-none motion-reduce:data-dragging:scale-100"
            />
          </SliderPrimitive.Track>
        </SliderPrimitive.Control>
      </SliderPrimitive.Root>
      {marks && marks.length ? (
        <div aria-hidden className="flex h-1 w-full gap-px overflow-hidden rounded-capsule" data-slot="slider-marks">
          {marks.map((mark, index) => (
            <span key={index} title={mark.title} className={cn("h-full min-w-0 flex-1", MARK[mark.tone])} />
          ))}
        </div>
      ) : null}
      {ends ? (
        <div className="flex items-center justify-between gap-3 text-2xs text-muted-foreground tabular-nums">
          <span>{ends[0]}</span>
          <span>{ends[1]}</span>
        </div>
      ) : null}
    </div>
  );
}

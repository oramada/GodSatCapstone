// The clock: play, where we are in time, how fast it runs, and the scrubber with the
// focused object's custody laid under it (one mark per saved epoch).

import {
  ChoiceSelect,
  Crossfade,
  GlassPanel,
  IconButton,
  Menu,
  MenuGroup,
  MenuGroupLabel,
  MenuItem,
  MenuPopup,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
  Slider,
  type SliderMark,
  Text,
} from "@sam/design-system";
import { setAppearance, useTheme, type Appearance } from "@sam/design-system/theme";
import { DownloadIcon, EllipsisIcon, PauseIcon, PlayIcon, RotateCcwIcon, ScanIcon, SunIcon, TargetIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { useEngine, useReadout, useStudio } from "../engine/context";
import type { CameraMode, Speed } from "../engine/studio";
import type { TrackStateName } from "../engine/types";
import { TONE } from "./tone";

const SPEEDS: { value: Speed; label: string }[] = [
  { value: "0.1", label: "Slow · 0.1 steps/s" },
  { value: "0.35", label: "0.35 steps/s" },
  { value: "1", label: "1 step/s" },
  { value: "3", label: "3 steps/s" },
];

const APPEARANCES: { value: Appearance; label: string }[] = [
  { value: "system", label: "Auto" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function PlaybackBar() {
  const engine = useEngine();
  const selected = useStudio((s) => s.selectedByUser);
  const boxSelection = useStudio((s) => s.boxSelection);
  const cameraMode = useStudio((s) => s.cameraMode);
  const playing = useStudio((s) => s.playing);
  const speed = useStudio((s) => s.speed);
  const max = useStudio((s) => s.scrubMax);
  const times = useStudio((s) => s.scene?.times);
  const states = useStudio((s) => s.marks);
  const windowed = useStudio((s) => !!s.scene?.sequence);
  const backend = useStudio((s) => s.computeBackend);
  const performance = useStudio((s) => s.framePerformance);
  const ready = useStudio((s) => !!s.scene);
  const global = useReadout((r) => r?.global ?? 0);
  const elapsed = useReadout((r) => r?.elapsed ?? "00:00");
  const utc = useReadout((r) => r?.utc ?? "UTC");
  const duration = useReadout((r) => r?.duration ?? "");
  const { appearance } = useTheme();
  // Where the thumb is while it's held: a saved window can take a moment to arrive, and the
  // thumb mustn't jump back to the old time meanwhile.
  const [held, setHeld] = useState<number | null>(null);
  if (held !== null && Math.abs(global - held) < 0.005) setHeld(null);

  const marks = useMemo<SliderMark[] | undefined>(
    () =>
      states && times
        ? states.map((state: TrackStateName, i) => ({ tone: TONE[state], title: `${times[i] ?? ""}: ${state}` }))
        : undefined,
    [states, times],
  );

  return (
    <GlassPanel
      padding="bar"
      className="fixed inset-x-2 bottom-2 z-20 flex flex-col gap-1.5 sm:inset-x-auto sm:bottom-6 sm:left-1/2 sm:w-full sm:max-w-xl sm:-translate-x-1/2"
    >
      <div className="flex items-center gap-2">
        <IconButton
          label={playing ? "Pause animation" : "Play animation"}
          size="md"
          variant="primary"
          shape="circle"
          shortcut="space"
          disabled={!ready}
          onClick={() => engine.togglePlay()}
        >
          <Crossfade>{playing ? <PauseIcon key="pause" /> : <PlayIcon key="play" />}</Crossfade>
        </IconButton>
        <div className="flex min-w-0 flex-col">
          <Text as="span" weight="semibold" numeric>
            {elapsed}
          </Text>
          <Text as="span" size="2xs" tone="muted" numeric truncate>
            {utc}
          </Text>
        </div>
        <ChoiceSelect
          label="Playback speed"
          value={speed}
          options={SPEEDS}
          onChange={(next) => engine.setSpeed(next)}
          className="studio-hud-select ms-auto hidden sm:flex sm:w-36"
        />
        <Menu>
          <MenuTrigger
            render={
              <IconButton label="View options" tooltip={false} className="ms-auto sm:ms-0">
                <EllipsisIcon />
              </IconButton>
            }
          />
          <MenuPopup align="end" side="top">
            <MenuItem onClick={() => engine.resetView()}>
              <RotateCcwIcon />
              Reset view
            </MenuItem>
            <MenuItem disabled={!ready} onClick={() => engine.lookAtSun()}>
              <SunIcon />
              Look at Sun
            </MenuItem>
            <MenuItem disabled={!selected} onClick={() => engine.followSatellite()}>
              <TargetIcon />
              Zoom to satellite
            </MenuItem>
            <MenuItem disabled={!ready} onClick={() => engine.setBoxSelection(!boxSelection)}>
              <ScanIcon />
              {boxSelection ? "Exit box selection" : "Box select satellites"}
            </MenuItem>
            <MenuGroup>
              <MenuGroupLabel>Camera</MenuGroupLabel>
              <MenuRadioGroup value={cameraMode} onValueChange={(next) => engine.setCameraMode(next as CameraMode)}>
                <MenuRadioItem value="orbit">Orbit</MenuRadioItem>
                <MenuRadioItem value="free" disabled={!ready}>Free flight</MenuRadioItem>
              </MenuRadioGroup>
            </MenuGroup>
            <MenuSeparator />
            <MenuItem disabled={!ready} onClick={() => engine.exportScene()}>
              <DownloadIcon />
              {windowed ? "Export window" : "Export scene"}
            </MenuItem>
            {/* On a phone the speed lives here, so the UTC time has the row. */}
            <MenuSeparator className="sm:hidden" />
            <MenuGroup className="sm:hidden">
              <MenuGroupLabel>Playback speed</MenuGroupLabel>
              <MenuRadioGroup value={speed} onValueChange={(next) => engine.setSpeed(next as Speed)}>
                {SPEEDS.map((option) => (
                  <MenuRadioItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuRadioItem>
                ))}
              </MenuRadioGroup>
            </MenuGroup>
            <MenuSeparator />
            <MenuGroup>
              <MenuGroupLabel>Appearance</MenuGroupLabel>
              <MenuRadioGroup value={appearance} onValueChange={(next) => setAppearance(next as Appearance)}>
                {APPEARANCES.map((option) => (
                  <MenuRadioItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuRadioItem>
                ))}
              </MenuRadioGroup>
            </MenuGroup>
            <MenuSeparator />
            <MenuGroup>
              <MenuGroupLabel>{backend}</MenuGroupLabel>
              {performance ? <MenuGroupLabel detail>{performance}</MenuGroupLabel> : null}
            </MenuGroup>
          </MenuPopup>
        </Menu>
      </div>
      <Slider
        label="Scene timeline"
        value={Math.min(held ?? global, max)}
        max={max}
        step={0.01}
        // Shift+Arrow and Page Up/Down move one saved epoch; the arrows alone, a hundredth of one.
        largeStep={1}
        disabled={!ready}
        onChange={(next) => {
          setHeld(next);
          engine.scrub(next);
        }}
        onCommit={() => setHeld(null)}
        // The clock's words once it has reached the value; the saved epoch while it catches up.
        valueText={(value) =>
          Math.abs(value - global) < 0.005 ? `${elapsed}, ${utc}` : `Saved epoch ${Math.round(value) + 1} of ${Math.round(max) + 1}`
        }
        {...(marks ? { marks } : {})}
        ends={["Start", duration]}
      />
    </GlassPanel>
  );
}

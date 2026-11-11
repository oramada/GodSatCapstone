// A new orbit experiment: initial states, time and resolution, force models, spacecraft
// properties and atmosphere inputs, validated by the service before it runs locally. The
// payload that runs is the one that was validated (compared as JSON). A running job is polled
// every second and remembered for this tab, so closing the panel or reloading keeps it. A trail
// at the foot says where the experiment is (set up, validate, run, open), and ⌘/Ctrl+Enter runs
// a validated setup. Ported from web/studio/experiment-panel.js.

import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogPopup,
  AlertDialogTitle,
  Button,
  ChoiceSelect,
  EmptyState,
  Field,
  IconButton,
  Input,
  ListGroup,
  ListRow,
  LoadingState,
  ProgressMeter,
  Reveal,
  SectionHeader,
  Separator,
  StatTile,
  StatusLine,
  type StatusLineTone,
  StepTrail,
  type StepTrailState,
  Switch,
} from "@sam/design-system";
import {
  ArrowRightIcon,
  AtomIcon,
  BoxIcon,
  DownloadIcon,
  GlobeIcon,
  PlayIcon,
  RocketIcon,
  RotateCwIcon,
  ServerOffIcon,
  ShieldCheckIcon,
  SlidersHorizontalIcon,
  SquareIcon,
  TimerIcon,
  WindIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";

import { Fine, Panel } from "../components/Panel";
import { PANEL_ICON } from "../components/icons";
import { download, getJson, messageOf, postJson } from "../engine/api";
import { buildExperiment, type ExperimentValues } from "../engine/legacy";

const BASE = "/api/studio/experiments/";
const JOB_KEY = "godsat.last-job";
const SYNTHETIC = "synthetic";
const NO_DRIVER = "none";

interface Options {
  token: string;
  templates: { id: string; name: string }[];
  drivers: { id: string; name: string }[];
}
interface Template {
  epoch: string;
  duration_seconds: number;
  integration_step_seconds: number;
  output_step_seconds: number;
  objects: unknown[];
  forces?: Record<string, boolean>;
  gravity_model?: unknown;
}
interface Summary {
  objects: number;
  frames: number;
  duration_seconds: number;
  forces: string[];
  note: string;
}
interface Job {
  id: string;
  status: "running" | "succeeded" | "cancelled" | "failed";
  started: number;
  scene_id?: string;
  output?: string;
  error?: string;
  summary?: { objects: number };
  result?: { elapsed_seconds: number };
}

/** The service stops an interactive run after this long (godsat/studio/experiments.py). */
const RUN_LIMIT_SECONDS = 180;

const STEPS = [
  { id: "setup", icon: <SlidersHorizontalIcon />, title: "Set up", detail: "Initial states, time and forces" },
  { id: "validate", icon: <ShieldCheckIcon />, title: "Validate", detail: "Bounds and data coverage" },
  { id: "run", icon: <PlayIcon />, title: "Run", detail: "Locally, up to 3 minutes" },
  { id: "open", icon: <GlobeIcon />, title: "Open result", detail: "On the globe" },
] as const;

const FORCE_NAMES: Record<string, string> = {
  j2: "J2 gravity",
  zonal_gravity: "Zonal gravity",
  third_bodies: "Sun/Moon gravity",
  solar_radiation_pressure: "Solar pressure",
  schwarzschild: "Relativity",
  drag: "Atmospheric drag",
};

type Gravity = ExperimentValues["gravity"];
type NumberField = "count" | "altitude" | "inclination" | "duration" | "step" | "cadence" | "mass" | "dragArea" | "cd" | "radiationArea" | "cr";

interface Form {
  template: string;
  epoch: string;
  numbers: Record<NumberField, string>;
  gravity: Gravity;
  thirdBodies: boolean;
  srp: boolean;
  relativity: boolean;
  drag: boolean;
  applyProperties: boolean;
  driver: string;
}

const INITIAL: Form = {
  template: SYNTHETIC,
  epoch: "2026-11-08T18:55:00Z",
  numbers: { count: "100", altitude: "400", inclination: "53", duration: "10", step: "10", cadence: "30", mass: "120", dragArea: "1.2", cd: "2.2", radiationArea: "1.2", cr: "1.3" },
  gravity: "zonal",
  thirdBodies: true,
  srp: true,
  relativity: true,
  drag: false,
  applyProperties: true,
  driver: NO_DRIVER,
};

type Status = { text: string; tone: StatusLineTone };
type Service = "loading" | "ready" | "failed";

/** The service forgets jobs when it restarts (they live in its memory). */
const LOST_JOB = /Unknown simulation job/;

function forgetJob() {
  try {
    sessionStorage.removeItem(JOB_KEY);
  } catch {
    // Storage is unavailable: nothing to forget.
  }
}

/** Minutes for the duration field without float noise (250 s is 4.16666666667, not …0003). */
function minutes(seconds: number): string {
  return String(Number((seconds / 60).toPrecision(12)));
}

export function ExperimentPanel({
  onOpenResult,
  ...props
}: {
  open: boolean;
  onClose: () => void;
  headingRef: (node: HTMLHeadingElement | null) => void;
  trigger: RefObject<HTMLElement | null>;
  onOpenResult: (sceneId: string) => void;
}) {
  const [options, setOptions] = useState<Options | null>(null);
  const [service, setService] = useState<Service>("loading");
  const [serviceError, setServiceError] = useState("");
  /** A saved template being read: the picker shows it, Validate and Run wait for it. */
  const [loadingTemplate, setLoadingTemplate] = useState<string | null>(null);
  const [form, setForm] = useState<Form>(INITIAL);
  const [template, setTemplate] = useState<Template | null>(null);
  const [validated, setValidated] = useState<string | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [status, setStatus] = useState<Status>({ text: "", tone: "" });
  const [job, setJob] = useState<Job | null>(null);
  const [validating, setValidating] = useState(false);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  /** Open result shows for a finished run until the settings change. */
  const [openable, setOpenable] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const serial = useRef(0);
  const templateSerial = useRef(0);
  const mounted = useRef(true);
  const poll = useRef(0);
  const jobRef = useRef<Job | null>(null);

  const say = (text: string, error = false) => setStatus({ text, tone: error ? "error" : "" });
  /** A success the person waited on: the line pulses once (rule 8). */
  const done = (text: string) => setStatus({ text, tone: "ok" });
  const running = job?.status === "running";
  const busy = running || starting;
  // A run that ends while "Stop this run?" is open closes the dialog for good, so the next
  // run doesn't find it waiting.
  useEffect(() => {
    if (!running) setConfirmCancel(false);
  }, [running]);
  // Cancel run takes its own button away when the run stops; if focus went with it, it
  // lands on Run simulation instead of falling to the page.
  const runButton = useRef<HTMLButtonElement>(null);
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running && document.activeElement === document.body) runButton.current?.focus();
    wasRunning.current = running;
  }, [running]);

  const request = useCallback(
    <T,>(path: string, payload?: unknown) =>
      payload === undefined ? getJson<T>(BASE + path) : postJson<T>(BASE + path, payload, options?.token ?? ""),
    [options],
  );

  // A job's state in words; a running one is checked again in a second.
  const show = useCallback(
    (next: Job, read: (path: string) => Promise<Job>) => {
      clearTimeout(poll.current);
      jobRef.current = next;
      setJob(next);
      if (next.status === "running") {
        setElapsed(Math.max(0, Math.round(Date.now() / 1000 - next.started)));
        // Said once: the seconds count on the meter, not in the spoken line.
        say("Running. You can close this panel. The run will continue.");
        const check = () => {
          read(`job?id=${encodeURIComponent(next.id)}`)
            .then((latest) => show(latest, read))
            .catch((error: unknown) => {
              const message = messageOf(error);
              if (LOST_JOB.test(message)) {
                lose();
                return;
              }
              say(`Couldn't check the run: ${message}. Trying again in 3 seconds.`, true);
              poll.current = window.setTimeout(check, 3000);
            });
        };
        poll.current = window.setTimeout(check, 1000);
      } else if (next.status === "succeeded") {
        setOpenable(true);
        done(
          `Last run: ${(next.summary?.objects ?? 0).toLocaleString()} spacecraft completed in ${(next.result?.elapsed_seconds ?? 0).toFixed(1)} s. Saved to ${next.output ?? "the outputs folder"}.`,
        );
      } else if (next.status === "cancelled") {
        say("Simulation stopped. No result was opened.");
      } else {
        say(next.error || "Couldn't finish the simulation. Check the setup, then run it again.", true);
      }
    },
    // `lose` only reads refs and setters.
    [],
  );

  /** The service restarted and forgot the run: stop waiting on it and take its new session. */
  function lose() {
    clearTimeout(poll.current);
    jobRef.current = null;
    setJob(null);
    forgetJob();
    say("Lost track of the run: the Studio service restarted. Its output, if any, is in the library.", true);
    void connect();
  }

  /** Reads the service's options (and its session token); called on mount and to try again. */
  const connect = useCallback(async () => {
    setService("loading");
    try {
      const loaded = await getJson<Options>(`${BASE}options`);
      if (!mounted.current) return null;
      setOptions(loaded);
      setService("ready");
      setStatus((current) => (current.text ? current : { text: "Configure, then validate before running.", tone: "" }));
      return loaded;
    } catch (error) {
      if (mounted.current) {
        setServiceError(messageOf(error));
        setService("failed");
      }
      return null;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const read = (path: string) => getJson<Job>(BASE + path);
    (async () => {
      const loaded = await connect();
      if (!loaded || !mounted.current) return;
      let saved: string | null = null;
      try {
        saved = sessionStorage.getItem(JOB_KEY);
      } catch {
        saved = null;
      }
      if (!saved) return;
      try {
        const restored = await read(`job?id=${encodeURIComponent(saved)}`);
        if (mounted.current) show(restored, read);
      } catch {
        forgetJob();
      }
    })();
    return () => {
      mounted.current = false;
      clearTimeout(poll.current);
    };
  }, [connect, show]);

  /** Any edit: the last validation no longer stands. */
  const invalidate = () => {
    serial.current += 1;
    setValidating(false);
    setValidated(null);
    setSummary(null);
    if (jobRef.current?.status !== "running") {
      setOpenable(false);
      say("Settings changed. Validate before running.");
    }
  };

  const edit = (patch: Partial<Form>) => {
    setForm((current) => ({ ...current, ...patch }));
    invalidate();
  };
  const editNumber = (key: NumberField, value: string) => {
    setForm((current) => ({ ...current, numbers: { ...current.numbers, [key]: value } }));
    invalidate();
  };

  // The picked template and its config change together, once the config has arrived, so what
  // the picker shows is always what validates and runs. A later pick wins over an earlier one.
  const chooseTemplate = async (id: string) => {
    invalidate();
    const run = ++templateSerial.current;
    if (id === SYNTHETIC) {
      setLoadingTemplate(null);
      setTemplate(null);
      setForm((current) => ({ ...current, template: SYNTHETIC, gravity: "zonal" }));
      return;
    }
    setLoadingTemplate(id);
    say("Reading the saved initial states…");
    try {
      const config = await request<Template>(`template?id=${encodeURIComponent(id)}`);
      if (run !== templateSerial.current) return;
      invalidate();
      setTemplate(config);
      const forces = config.forces ?? {};
      setForm((current) => ({
        ...current,
        template: id,
        epoch: config.epoch,
        numbers: {
          ...current.numbers,
          duration: minutes(config.duration_seconds),
          step: String(config.integration_step_seconds),
          cadence: String(config.output_step_seconds),
        },
        gravity: forces.zonal_gravity ? "saved" : forces.j2 ? "j2" : "point",
        drag: !!forces.drag,
        thirdBodies: !!forces.third_bodies,
        srp: !!forces.solar_radiation_pressure,
        relativity: !!forces.schwarzschild,
        applyProperties: false,
      }));
      say(`${config.objects.length.toLocaleString()} saved initial states. Their coordinates and source metadata will be retained.`);
    } catch (error) {
      // The last good pick stays; only this one failed.
      if (run === templateSerial.current) say(messageOf(error), true);
    } finally {
      if (run === templateSerial.current) setLoadingTemplate(null);
    }
  };

  const payload = () => {
    if (!formRef.current?.reportValidity()) throw new Error("Complete the highlighted fields.");
    const n = (key: NumberField) => Number(form.numbers[key]);
    const values: ExperimentValues = {
      epoch: form.epoch,
      duration: n("duration"),
      step: n("step"),
      cadence: n("cadence"),
      count: n("count"),
      altitude: n("altitude"),
      inclination: n("inclination"),
      gravity: form.gravity,
      drag: form.drag,
      thirdBodies: form.thirdBodies,
      srp: form.srp,
      relativity: form.relativity,
      applyProperties: form.applyProperties,
      mass: n("mass"),
      dragArea: n("dragArea"),
      cd: n("cd"),
      radiationArea: n("radiationArea"),
      cr: n("cr"),
    };
    return { config: buildExperiment(values, template), driver_id: form.driver === NO_DRIVER ? "" : form.driver };
  };

  const validate = async () => {
    const run = ++serial.current;
    setValidated(null);
    setValidating(true);
    say("Validating model, bounds and source coverage…");
    try {
      const body = payload();
      const result = await request<{ summary: Summary }>("validate", body);
      if (run !== serial.current) return;
      setValidated(JSON.stringify(body));
      setSummary(result.summary);
      done("Validated. Ready to run a new local simulation.");
    } catch (error) {
      if (run === serial.current) say(messageOf(error), true);
    } finally {
      // A validation overtaken by an edit or a newer one leaves the newer one's state alone.
      if (run === serial.current) setValidating(false);
    }
  };

  const runSimulation = async () => {
    try {
      const body = payload();
      if (validated !== JSON.stringify(body)) {
        invalidate();
        throw new Error("Settings changed. Validate them again before running.");
      }
      setStarting(true);
      setJob(null);
      jobRef.current = null;
      say("Starting local simulation…");
      const started = await request<Job>("run", body);
      try {
        sessionStorage.setItem(JOB_KEY, started.id);
      } catch {
        // The run still goes on; only a reload forgets it.
      }
      show(started, (path) => request<Job>(path));
    } catch (error) {
      say(messageOf(error), true);
      // The service restarted under us: take its new session so the next press works.
      if (/Session changed/.test(messageOf(error))) void connect();
    } finally {
      setStarting(false);
    }
  };

  const cancelRun = async () => {
    setConfirmCancel(false);
    const current = jobRef.current;
    if (!current) return;
    setCancelling(true);
    try {
      show(await request<Job>("cancel", { id: current.id }), (path) => request<Job>(path));
    } catch (error) {
      say(messageOf(error), true);
    } finally {
      setCancelling(false);
    }
  };

  const exportSetup = () => {
    try {
      download("experiment-config.json", JSON.stringify(payload().config, null, 2), "application/json");
    } catch (error) {
      say(messageOf(error), true);
    }
  };

  const templates = useMemo(
    () => [{ value: SYNTHETIC, label: "Generate a synthetic constellation" }, ...(options?.templates ?? []).map((t) => ({ value: t.id, label: t.name }))],
    [options],
  );
  const drivers = useMemo(
    () => [{ value: NO_DRIVER, label: "Choose a local space-weather file" }, ...(options?.drivers ?? []).map((d) => ({ value: d.id, label: d.name }))],
    [options],
  );
  const gravities = useMemo(
    () => [
      { value: "point" as const, label: "Point mass" },
      { value: "j2" as const, label: "Point mass + J2" },
      { value: "zonal" as const, label: "WGS-84 zonal J2–J4" },
      ...(template?.gravity_model ? [{ value: "saved" as const, label: "Preserve saved zonal model" }] : []),
    ],
    [template],
  );

  // Where the experiment is: the trail's one step on now.
  const ready = service === "ready" && !loadingTemplate;
  const at = validating ? 1 : busy ? 2 : job?.status === "succeeded" && openable ? 3 : validated ? 2 : 0;
  const steps = STEPS.map((step, i) => ({ ...step, state: (i < at ? "done" : i === at ? "now" : "next") as StepTrailState }));
  // The validation summary wipes in and out; it keeps its last words while it leaves.
  const [shownSummary, setShownSummary] = useState(summary);
  if (summary && summary !== shownSummary) setShownSummary(summary);

  const resultReady = !busy && openable && job?.status === "succeeded" && !!job.scene_id;
  const saved = !!template;
  const number = (key: NumberField, label: string, unit: string | null, limits: { min: string; max?: string; step?: string }) => (
    <Field label={unit ? `${label} (${unit})` : label} htmlFor={`exp-${key}`}>
      <Input
        id={`exp-${key}`}
        type="number"
        size="sm"
        required
        min={limits.min}
        {...(limits.max ? { max: limits.max } : {})}
        step={limits.step ?? "any"}
        value={form.numbers[key]}
        onChange={(event) => editNumber(key, event.target.value)}
      />
    </Field>
  );
  const force = (key: "thirdBodies" | "srp" | "relativity" | "drag", title: string) => (
    <ListRow inline title={title} control={<Switch aria-label={title} checked={form[key]} onCheckedChange={(checked) => edit({ [key]: checked })} />} />
  );

  return (
    <Panel
      id="experiment-panel"
      icon={PANEL_ICON.experiment}
      eyebrow="Numerical simulation"
      title="New experiment"
      label="Experiment setup" closeLabel="Close experiment setup"
      side="left"
      {...props}
    >
      <Fine>Define an orbit experiment, validate its inputs, then run it locally.</Fine>
      {!options && service === "loading" ? <LoadingState variant="lines" label="Loading the experiment service" /> : null}
      {!options && service === "failed" ? (
        <EmptyState
          size="compact"
          icon={<ServerOffIcon />}
          title="Couldn't reach the experiment service"
          description={serviceError}
          action={
            <Button size="sm" onClick={() => void connect()}>
              <RotateCwIcon />
              Try again
            </Button>
          }
        />
      ) : null}
      {options ? (
        <>
          <form
            ref={formRef}
            onSubmit={(event) => {
              event.preventDefault();
              if (ready && !busy && !validating) void validate();
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || !(event.metaKey || event.ctrlKey) || busy || !validated || !ready) return;
              event.preventDefault();
              void runSimulation();
            }}
          >
            <fieldset disabled={busy} className="flex min-w-0 flex-col gap-5">
              <Section icon={<RocketIcon />} title="Initial states">
                <Field label="Starting point" htmlFor="exp-template">
                  <ChoiceSelect id="exp-template" value={loadingTemplate ?? form.template} options={templates} onChange={(id) => void chooseTemplate(id)} className="sm:w-full" />
                </Field>
                {saved ? (
                  <Fine>Saved osculating coordinates and provenance are retained. The epoch below applies to those coordinates.</Fine>
                ) : (
                  <div className="grid grid-cols-3 items-end gap-3">
                    {number("count", "Spacecraft", null, { min: "1", max: "2000", step: "1" })}
                    {number("altitude", "Altitude", "km", { min: "150", max: "36000" })}
                    {number("inclination", "Inclination", "°", { min: "0", max: "180" })}
                  </div>
                )}
                <Field label="Epoch" hint="UTC, ISO 8601 with Z or offset" htmlFor="exp-epoch">
                  <Input id="exp-epoch" size="sm" font="mono" required spellCheck={false} value={form.epoch} onChange={(event) => edit({ epoch: event.target.value })} />
                </Field>
                {saved ? null : <Fine>Generated constellations are hypothetical circular initial states. No measured orbit or observation history is implied.</Fine>}
              </Section>

              <Section icon={<TimerIcon />} title="Time and resolution">
                <div className="grid grid-cols-3 items-end gap-3">
                  {number("duration", "Duration", "min", { min: "0.001", max: "1440" })}
                  {number("step", "Integration step", "s", { min: "0.1", max: "30" })}
                  {number("cadence", "Saved cadence", "s", { min: "0.1" })}
                </div>
                <Fine>Cadence must divide duration and be a multiple of the integration step. Smaller steps should be checked for convergence.</Fine>
              </Section>

              <Section icon={<AtomIcon />} title="Force models">
                <Field label="Earth gravity" htmlFor="exp-gravity">
                  <ChoiceSelect id="exp-gravity" value={form.gravity} options={gravities} onChange={(gravity) => edit({ gravity })} className="sm:w-full" />
                </Field>
                <ListGroup>
                  {force("thirdBodies", "Sun and Moon gravity")}
                  {force("srp", "Solar radiation and eclipses")}
                  {force("relativity", "Schwarzschild correction")}
                  {force("drag", "Atmospheric drag · NRLMSIS")}
                </ListGroup>
                <Fine>Constant-area solar-pressure model. Spherical Earth shadow. Gravity is zonal only. These are optional approximations, not full orbit determination.</Fine>
              </Section>

              <Section icon={<BoxIcon />} title="Spacecraft properties">
                {saved ? (
                  <ListGroup>
                    <ListRow
                      inline
                      title="Override every spacecraft"
                      control={
                        <Switch
                          aria-label="Override every spacecraft"
                          checked={form.applyProperties}
                          onCheckedChange={(checked) => edit({ applyProperties: checked })}
                        />
                      }
                    />
                  </ListGroup>
                ) : null}
                <fieldset disabled={saved && !form.applyProperties} className="grid min-w-0 grid-cols-2 items-end gap-3 sm:grid-cols-3">
                  {number("mass", "Mass", "kg", { min: "0.001" })}
                  {number("dragArea", "Drag area", "m²", { min: "0.000001" })}
                  {number("cd", "Drag coefficient", null, { min: "0.001" })}
                  {number("radiationArea", "Radiation area", "m²", { min: "0.000001" })}
                  {number("cr", "Radiation coefficient", null, { min: "0.001" })}
                </fieldset>
                <Fine>Effective areas and coefficients are inputs. They aren’t inferred from the displayed spacecraft shape.</Fine>
              </Section>

              <Section icon={<WindIcon />} title="Atmosphere inputs">
                {form.drag ? (
                  <Field label="Local space-weather data" htmlFor="exp-driver">
                    <ChoiceSelect id="exp-driver" value={form.driver} options={drivers} onChange={(driver) => edit({ driver })} className="sm:w-full" />
                  </Field>
                ) : null}
                <Fine>
                  Drag uses local F10.7 and Ap history. Validation checks coverage for the entire run. Missing drivers are never filled
                  automatically. Displayed clouds, magnetic and ionospheric layers aren’t drag inputs.
                </Fine>
              </Section>
            </fieldset>
          </form>

          <Separator />
          <div className="flex flex-col gap-3">
            <StepTrail steps={steps} size="compact" arrive={false} aria-label="Experiment progress" />
            <Reveal open={!!summary} from="top">
              {shownSummary ? (
                <div className="flex flex-col gap-2">
                  <div className="grid grid-cols-3 gap-2">
                    <StatTile variant="inset" size="sm" label="Spacecraft" value={shownSummary.objects.toLocaleString()} />
                    <StatTile variant="inset" size="sm" label="Saved epochs" value={shownSummary.frames.toLocaleString()} />
                    <StatTile variant="inset" size="sm" label="Duration" value={`${minutes(shownSummary.duration_seconds)} min`} />
                  </div>
                  <Fine>{shownSummary.forces.map((key) => FORCE_NAMES[key] ?? key).join(" · ")}</Fine>
                  <Fine>{shownSummary.note}</Fine>
                </div>
              ) : null}
            </Reveal>
            {running ? (
              <div className="motion-enter flex flex-col gap-1.5">
                <ProgressMeter
                  value={Math.min(elapsed, RUN_LIMIT_SECONDS)}
                  max={RUN_LIMIT_SECONDS}
                  label="Time used of the 3-minute run limit"
                  valueText={`${elapsed} of ${RUN_LIMIT_SECONDS} seconds`}
                  tone={elapsed > RUN_LIMIT_SECONDS * 0.8 ? "warning" : "primary"}
                  size="sm"
                />
                <Fine>{elapsed} of {RUN_LIMIT_SECONDS} seconds used</Fine>
              </div>
            ) : null}
            <StatusLine text={status.text} tone={status.tone} />
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" loading={validating} disabled={!ready || busy || validating} onClick={() => void validate()}>
                <ShieldCheckIcon />
                Validate
              </Button>
              {running ? (
                <Button variant="destructive-outline" size="sm" loading={cancelling} disabled={cancelling} onClick={() => setConfirmCancel(true)}>
                  <SquareIcon />
                  Stop run
                </Button>
              ) : (
                <Button
                  ref={runButton}
                  size="sm"
                  // One main action at a time: once a result is ready to open, opening it is.
                  variant={resultReady ? "outline" : "default"}
                  kbd="mod+enter"
                  loading={starting}
                  disabled={busy || !validated || !ready}
                  onClick={() => void runSimulation()}
                >
                  <PlayIcon />
                  Run simulation
                </Button>
              )}
              {resultReady ? (
                <span className="motion-enter">
                  <Button size="sm" onClick={() => job?.scene_id && onOpenResult(job.scene_id)}>
                    Open result
                    <ArrowRightIcon />
                  </Button>
                </span>
              ) : null}
              <IconButton label="Export setup" size="sm" className="ms-auto" disabled={busy} onClick={exportSetup}>
                <DownloadIcon />
              </IconButton>
            </div>
            <AlertDialog open={confirmCancel && running} onOpenChange={setConfirmCancel}>
              <AlertDialogPopup>
                <AlertDialogHeader>
                  <AlertDialogTitle>Stop this run?</AlertDialogTitle>
                  <AlertDialogDescription>
                    The simulation stops now and no result is opened. Files it already wrote stay in its run folder. Your setup stays as it is.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                  <Button variant="destructive" onClick={() => void cancelRun()}>
                    <SquareIcon />
                    Stop run
                  </Button>
                </AlertDialogFooter>
              </AlertDialogPopup>
            </AlertDialog>
            <Fine>Local execution · up to 2,000 spacecraft and 2 million integration steps · 1 run at a time · 3-minute limit.</Fine>
          </div>
        </>
      ) : null}
    </Panel>
  );
}

function Section({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <SectionHeader inset={false} as="h3" icon={icon} title={title} />
      {children}
    </section>
  );
}

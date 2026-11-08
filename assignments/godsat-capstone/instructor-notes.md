# Instructor notes — keep separate from student distribution

## Scope and source adaptation

Prepared November 8, 2026. The requested GoDSAT assignment replaces the capstone PDF's default vehicle-loan task. This is a deliberate assignment adaptation, not a claim that the original capstone already permits unrestricted substitution. No additional approval step is imposed by the handout. Official course announcements still determine deadlines and team size.

Preserved from the capstone: DOE → refinement → ablation → distillation/compression → multi-objective selection; locked controls; statistical plus ML evidence; approximately 800-word proposal; 6–8 page paper; reproducibility package; 8–12 minute talk; responsible-use appendix. Rubric weights retain 20/15/20/15/15/10/5. Eight of the 20 ML/system-evidence points are assigned explicitly to the requested uplink question. Optional bonus adds up to 10 points, reported separately.

Preserved from the GoDSAT research direction: seven factors and linear ranges; 16-run resolution-IV screen; 15-point face-centered CCD core; independent five-seed evaluation; custody, energy and false-track responses. Extra center retraining repairs the lack of pure-error replication. The paper's 31-treatment BO comparison is not mandatory in this teaching adaptation: it is not needed for the capstone spine and would add substantial compute. It may be assigned as an additional comparator only with an explicit budget and grading revision. No manuscript gain is a grading target.

## Uplink answer key

All given communication parameters are hypothetical, not an Iridium specification.

- Payload = 4,096 bytes × 8 = 32,768 bits.
- On-wire bits = 32,768 × 1.25 = 40,960 bits. Here “25% overhead” means overhead relative to payload, not 25% of total bits.
- Serialization = 40,960 / 64,000 = **0.640 s**.
- Propagation = 1,500,000 / 299,792,458 = **0.0050034614 s**, or about **5.003 ms**.
- Total = 0 + 0.20 + 0.05 + 0.640 + 0.0050034614 + 0.01 = **0.9050034614 s**.
- The 0.80 s window is missed by about **0.1050 s**, even before adding decision time or acknowledgement. Serialization is the largest term. Propagation alone is an incorrect answer.
- An acknowledgement cannot repair the missed one-way deadline. Computing full acknowledgement latency requires its size/rate, return range, processing and scheduling assumptions. Do not accept “double the one-way total” without a justified symmetric protocol.
- A useful sufficient condition is T_decision + T_command_received + T_spacecraft_response + T_observation <= T_available, with each start/end event and overlap assumption stated. Add acknowledgement only when the protocol requires it before action. A store-and-forward schedule may need a different bound.
- At 10 slant TECU and 1.57542 GHz: excess range = **1.623724475 m**, time = **5.416161854 ns**. It is a group-delay example, not an outage calculation or a full LEO-column estimate. A small delay is compatible with other large degradations.

Q3 has no universal numerical answer: grade the saved geometry, time-window definition, resolution, measured actor timing, and whether the inequality matches the stated protocol. A 60-second simulation step cannot substantiate millisecond event timing without additional assumptions or finer event handling.

## DOE and RSM checks

For E=ABC, F=ABD, G=ACD, the defining relation is:

I = ABCE = ABDF = ACDG = AEFG = BCFG = BDEG = CDEF.

All nonidentity words have length four, hence resolution IV. Main effects are aliased with three-factor or higher terms. The seven two-factor groups are:

- AB = CE = DF
- AC = BE = DG
- AD = BF = CG
- AE = BC = FG
- AF = BD = EG
- AG = CD = EF
- BG = CF = DE

These list the two-factor members, not each full eight-member alias chain. Students should generate the full chains, including higher-order aliases. One further independent contrast has minimum alias order three. Pooling unresolved interactions is an assumption, not replicated noise.

For an identifiable 10-coefficient quadratic: 15 distinct design points and one observation each give 5 residual df and zero pure-error df. Adding two independent center retrains gives n=17, 15 distinct points, residual df=7, pure-error df=2 and lack-of-fit df=5. With so little pure-error replication the test can have low power; non-rejection is not proof of correctness. Integer decoding or rank deficiency requires recalculation.

## Source and runtime readiness

Inspected source HEAD: `938e90c594915b88542b8c9a1c6a0f5c285d0d16`, plus pre-existing local edits and untracked simulation files. That commit alone does not contain the complete working snapshot referenced by the bonus section. Archive the working tree or commit/release the intended materials before distributing the assignment. Existing changes were preserved.

Verified source interfaces: `godsat/design.py` contains screening, aliases, CCD and surface routines; `learning.py` supplies Agent/train; `sensorphysics.py` supplies modeled ground tracking; `simulation/links.py` supplies selected propagation estimates. The simulation layer does not provide complete link budgets, measured weather-caused tracking losses, packet scheduling, or a ready-made compression pipeline. These are student extensions, not advertised existing functions.

The general `campaign --quick` command is a smoke check. `scripts.experiments.run_iridium_ground_study` is the fuller registered study runner, documented in `docs/setup.md`. It may be too costly for every student. Set budgets from an instructor pilot run on the intended hardware; do not promise a laptop completion time based only on treatment count. Allow a smaller predeclared episode budget uniformly if needed, but retain baselines, independent confirmation, ablation and compression. Label it a teaching adaptation.

Both supplied PDFs were extracted in full. The assignment was compiled and its eight pages rendered for visual inspection. Formula arithmetic and design algebra were independently checked. The campaign and student extensions were not run as part of document authoring.

## Source files used

- `/Users/omarramadan/Downloads/Capstone__End_to_End_Neural_Network_Optimization.pdf`
- `/Users/omarramadan/Downloads/Systematic_Hyperparameter_Optimization_of_GoDSAT_Sensor_Tasking_Agents_via_Fractional_Factorial_Design_and_Response_Surface_Methodology.pdf`
- Current repository setup, factor definitions, study audit, neural model, sensor and simulation documentation/source.
- ESA Navipedia “Ionospheric Delay,” ITU-R P.531 and ITU-R P.618, linked in the handout.

The remote Overleaf project could not be accessed and was not modified. Upload the student ZIP there manually if desired.

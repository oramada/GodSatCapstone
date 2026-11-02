# Source fidelity and implementation scope

The governing factorial/RSM design PDF was supplied on 2026-10-25 and is mapped in the [requirement audit](governing-pdf-audit.md). Its actor–critic description differs from the available original controller. The comparison below uses the original-framework source: `GoDSAT__Reinforcement_Learning_Based_Satellite_Constellation_Sensor_Tasking_Framework.pdf` in the local original-framework checkout. Its SHA-256 is `42f64a9e93bc916b94263101db8cdad4b1c89ebfce156f58b557d3f4bfbdee4c`; the source checkout is at commit `672dfec2a629bd8ceb58a36e54e5ec8dd93d0776`.

The source PDF's methodology, Table 1 and Algorithm 1 describe the original controller. The Python descriptions below come from the current implementation and executed configurations. This comparison establishes differences; the governing design requirements are now assessed separately against its actual text.

| Aspect | Available original-framework source | Executed Python study |
|---|---|---|
| Controller | Gradient following and discrete hill climbing using a pretrained 11-by-11 Q-table | A shared categorical neural actor, centralized critic and target critic; additional all-catalogue runs use a separate greedy urgency/slew scheduler |
| Custody coordination | Global latitude/longitude grid ownership during Q tracking; helper functions govern entry, maintenance and release | Angular claim features and per-target ownership prevent duplicate assignments in a step; these have not been shown equivalent to the original ClaimMap state machine |
| Constellation | Sixteen constructed satellites in two orbital planes | Six sensor hosts per regime, selected from a present-day active-payload cohort and backcast through historical elements |
| Targets | Twenty generated ballistic arcs in the source configuration | Eighteen archived orbital targets in learned-policy scenes; separate scale-extension runs include all fresh, usable catalogue targets |
| Time step | Two seconds | Sixty seconds in the executed principal campaigns |
| Pointing | Separate scan/track fields of view and one degree per second pointing-rate configuration | A range/line-of-sight/slew-constrained tasking model, configured at two degrees per second |
| Earth/orbit representation | Constructed classical orbital elements with Earth rotation and GRS80 geodetic helpers | Historical WGS-72 SGP4/TEME reconstruction; separate common-frame numerical force-model sensitivity checks |
| Evidence obtained here | A locally available upstream-derived Octave compatibility port freshly executed for one external trajectory and two seeds | Full configured screening, response-surface, BO and held-out runs plus separately audited orbit and dropout extensions |
| Fidelity limit | The compatibility port changes input handling, geodetic helpers and headless state updates; native MATLAB bitwise parity is unverified | Actor-critic performance is not established as original-framework performance, and the authorized simulation adaptation is assessed separately against the supplied design |

The fresh Octave execution reconciled custody ticks and retained the upstream Q-table bytes. Its two seeds yielded the same selected metrics. It uses a constructed constellation and an external target trajectory, so its custody ratio must not be pooled with historical orbital-tasking responses. The [execution receipt](../outputs/original-framework-reference-20261024/summary.json) identifies source files and port modifications.

A second local PDF, whose filename contains `godsat_at`, is titled *DataOps-to-Decision: Reproducible analytics for multi-sensor aircraft tracking with GoDSAT-AT*. Its abstract describes ADS-B aircraft encounters, Bayesian trajectory prediction and loss-of-separation screening. It is not the requested orbital-tasking factorial/RSM design. Its SHA-256 is `accbfe736507d7139138f2fd01e6fe5bb1b809e7fed6284c75f84e44aa0b6071`. The local `GodSAT/main.pdf` is another project and has not been adopted as the governing design either.

The source PDF has been read and mapped to implementation and executed evidence. The user authorized explicit baseline/sensor assumptions where the source supplies no reproducible specifications. This adaptation does not establish exact published-baseline reproduction. Numerical reproducibility of the current simulator cannot establish equivalence to another controller or source protocol.

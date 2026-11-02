# Simulated sensor-dropout study

Controlled simulated sensor outage intervention; synthetic sensor assumptions and historical orbital geometry, not observed sensor telemetry.

Frozen policy: `frozen DOE-recommended checkpoints; no retraining by dropout level`. Dates: 2022-10-15, 2023-01-15, 2023-04-15, 2023-07-15, 2023-10-15, 2024-01-15, 2024-04-15, 2024-07-15, 2024-10-15, 2025-01-15, 2025-04-15, 2025-07-15, 2025-10-15, 2026-01-15, 2026-04-15, 2026-07-15, 2026-10-01. Regimes: leo, meo, geo, heo. 20 paired simulation replicates per date, frozen checkpoint, and regime-condition across 5 frozen checkpoint(s).

Dropout is applied to eligible, conflict-free assigned observations. Custody is the fraction of modeled targets remaining within the configured custody interval. Slew is a normalized angle proxy; false-track is a failed-observation proxy. Neither represents calibrated hardware telemetry. Confidence intervals below treat the 17 sampled historical dates as independent clusters, averaging matched model checkpoints and simulation seeds within each date first.

| Orbit | Outage process | Requested rate | Observed rate | Mean custody | Custody change vs 0% (date-clustered 95% CI) |
|---|---|---:|---:|---:|---:|
| LEO | independent | 0% | 0.0% | 0.199 | +0.000 ± 0.000 |
| LEO | independent | 5% | 4.9% | 0.197 | -0.002 ± 0.000 |
| LEO | independent | 10% | 10.0% | 0.194 | -0.004 ± 0.000 |
| LEO | independent | 20% | 19.8% | 0.189 | -0.010 ± 0.001 |
| LEO | independent | 40% | 40.1% | 0.172 | -0.027 ± 0.002 |
| LEO | independent | 60% | 60.1% | 0.141 | -0.058 ± 0.003 |
| LEO | burst | 0% | 0.0% | 0.199 | +0.000 ± 0.000 |
| LEO | burst | 5% | 3.8% | 0.195 | -0.003 ± 0.000 |
| LEO | burst | 10% | 9.0% | 0.191 | -0.008 ± 0.001 |
| LEO | burst | 20% | 19.6% | 0.181 | -0.017 ± 0.001 |
| LEO | burst | 40% | 39.8% | 0.158 | -0.041 ± 0.003 |
| LEO | burst | 60% | 59.0% | 0.130 | -0.069 ± 0.005 |
| MEO | independent | 0% | 0.0% | 0.197 | +0.000 ± 0.000 |
| MEO | independent | 5% | 5.0% | 0.195 | -0.002 ± 0.000 |
| MEO | independent | 10% | 9.9% | 0.193 | -0.004 ± 0.000 |
| MEO | independent | 20% | 19.8% | 0.189 | -0.008 ± 0.001 |
| MEO | independent | 40% | 40.1% | 0.173 | -0.023 ± 0.002 |
| MEO | independent | 60% | 60.3% | 0.144 | -0.053 ± 0.004 |
| MEO | burst | 0% | 0.0% | 0.197 | +0.000 ± 0.000 |
| MEO | burst | 5% | 3.6% | 0.194 | -0.003 ± 0.001 |
| MEO | burst | 10% | 9.3% | 0.188 | -0.009 ± 0.001 |
| MEO | burst | 20% | 19.2% | 0.178 | -0.019 ± 0.002 |
| MEO | burst | 40% | 39.1% | 0.155 | -0.042 ± 0.004 |
| MEO | burst | 60% | 58.5% | 0.129 | -0.067 ± 0.006 |
| GEO | independent | 0% | 0.0% | 0.117 | +0.000 ± 0.000 |
| GEO | independent | 5% | 4.9% | 0.116 | -0.001 ± 0.000 |
| GEO | independent | 10% | 10.0% | 0.116 | -0.001 ± 0.000 |
| GEO | independent | 20% | 19.7% | 0.114 | -0.003 ± 0.001 |
| GEO | independent | 40% | 39.9% | 0.106 | -0.011 ± 0.002 |
| GEO | independent | 60% | 59.9% | 0.090 | -0.027 ± 0.004 |
| GEO | burst | 0% | 0.0% | 0.117 | +0.000 ± 0.000 |
| GEO | burst | 5% | 3.5% | 0.116 | -0.001 ± 0.000 |
| GEO | burst | 10% | 8.4% | 0.114 | -0.003 ± 0.001 |
| GEO | burst | 20% | 19.5% | 0.110 | -0.007 ± 0.001 |
| GEO | burst | 40% | 39.3% | 0.100 | -0.017 ± 0.003 |
| GEO | burst | 60% | 58.2% | 0.085 | -0.032 ± 0.005 |
| HEO | independent | 0% | 0.0% | 0.154 | +0.000 ± 0.000 |
| HEO | independent | 5% | 5.1% | 0.153 | -0.001 ± 0.000 |
| HEO | independent | 10% | 10.2% | 0.151 | -0.003 ± 0.000 |
| HEO | independent | 20% | 20.1% | 0.147 | -0.007 ± 0.001 |
| HEO | independent | 40% | 40.3% | 0.135 | -0.019 ± 0.002 |
| HEO | independent | 60% | 60.3% | 0.112 | -0.042 ± 0.005 |
| HEO | burst | 0% | 0.0% | 0.154 | +0.000 ± 0.000 |
| HEO | burst | 5% | 4.0% | 0.151 | -0.003 ± 0.001 |
| HEO | burst | 10% | 9.2% | 0.146 | -0.008 ± 0.001 |
| HEO | burst | 20% | 19.4% | 0.136 | -0.018 ± 0.002 |
| HEO | burst | 40% | 39.2% | 0.117 | -0.037 ± 0.005 |
| HEO | burst | 60% | 58.5% | 0.097 | -0.057 ± 0.008 |

At 20% burst dropout, paired custody-effect sensitivity to temporal dependence (bootstrap blocks are consecutive sampled dates):

| Orbit | Mean change | 3-date block 95% interval | 6-date block 95% interval | 12-date block 95% interval |
|---|---:|---:|---:|---:|
| LEO | -0.017 | [-0.018, -0.016] | [-0.018, -0.016] | [-0.018, -0.017] |
| MEO | -0.019 | [-0.020, -0.017] | [-0.020, -0.017] | [-0.020, -0.018] |
| GEO | -0.007 | [-0.008, -0.005] | [-0.008, -0.006] | [-0.007, -0.006] |
| HEO | -0.018 | [-0.020, -0.016] | [-0.020, -0.017] | [-0.019, -0.018] |

Moving-block intervals preserve short-range ordering within each resampled block and complement the date-clustered t intervals above.

Orbit classes use approximate mean-element bins, with high eccentricity taking precedence. This estimates one frozen policy’s response to injected sensor outages; it does not establish real sensor outage behavior, attitude knowledge, or operational constellation performance. The sampled dates are discrete historical snapshots, not continuous four-year playback.

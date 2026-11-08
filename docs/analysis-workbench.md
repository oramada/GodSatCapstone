# Orbital analysis workbench

Open Studio, choose **Data**, and expand **Orbital analysis workbench**.
All analysis uses the selected scene and its current loaded time window.

- **Telemetry:** interpolated position and geocentric radius. For ITRS scenes,
  WGS84 ellipsoidal latitude, longitude and altitude are derived from the current
  position. Speed is the magnitude of the supplied velocity at the preceding
  saved epoch; it remains in the declared frame. ITRS speed is Earth-fixed, not
  inertial orbital speed. Missing samples remain unavailable.
- **Ground track:** WGS84 sub-satellite coordinates at saved epochs, with gaps
  and dateline crossings separated. Non-ITRS scenes have no inferred ground track.
- **Watchlist:** up to twelve objects per scene source, saved in browser local
  storage. It shows current separation from the focused object. Select a watched
  name to focus it; objects absent from the current window remain unavailable.
- **Time navigation:** previous/next saved sample and exact ISO timestamp with
  an explicit UTC offset. Navigation is bounded to the current window, including
  when viewing a sequence. Existing global timeline controls still cross windows.
- **Closest sampled approaches:** compares the focus with all other objects at
  shared valid saved epochs. A cancellable Web Worker scans at most 20,000 objects
  and 1.2 million samples, reporting the smallest sampled separation per object.
  Threshold changes, source changes and focus changes invalidate prior results.
  At most 100 matching objects are displayed, ranked by sampled distance.
- **Exports:** telemetry for every saved epoch and the displayed screening results
  download as CSV. Missing quantities are blank; string values that might execute
  spreadsheet formulas are escaped. Source kind and reference frame are retained.

Sampled screening is not continuous-time conjunction analysis. Encounters between
saved epochs may be missed. The results have no covariance, probability of collision,
spacecraft dimensions, maneuver recommendation or operational alert interpretation.
They should not be used as collision predictions. Current-window scope is explicit;
results do not claim coverage of other sequence windows or the entire catalog epoch
history. Performance of the worker does not establish physical prediction accuracy.

Run `npm run test:studio` for geodetic, time-grid, gap, dateline, screening-bound,
large-catalog and CSV checks. Validate interactions in the browser, including source
changes during preparation, disabled exports before results, watchlist persistence,
missing data and exact timestamp navigation.

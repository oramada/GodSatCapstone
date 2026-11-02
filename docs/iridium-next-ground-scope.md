# Iridium NEXT and ground systems

The user restricted the participating systems on 2026-11-01 to Iridium NEXT and
ground systems, with an optional MEO constellation. Earlier mixed-catalogue and
LEO/MEO/GEO/HEO experiments remain preserved, but are not results for this scope.

## Orbital membership

The [dedicated CelesTrak NEXT group](https://celestrak.org/NORAD/elements/gp.php?GROUP=iridium-NEXT&FORMAT=json)
was downloaded. Its 80 listed spacecraft, including spares, are pinned by exact
NORAD IDs in `configs/iridium-next-membership.json`. This is not the broader
Iridium group or a text search for every catalogue name containing IRIDIUM.
Every pinned member also has payload type in the local SATCAT snapshot.

Only these 80 objects occur in the extracted
`data/iridium_next_orbit_history.parquet`: 290,075 historical element records.
The file receipt records membership/source/output hashes. Current group
membership does not prove historical operational status. In particular, the
presence of 80 objects does not mean 80 operational sensors or establish which
66 were operational at each epoch.

The active rule file is `configs/active-study-scope.json`. The default scenario
config is `configs/iridium-next-ground.json`. Until participant roles are fixed,
both orbital host and target candidates are constrained to NEXT as a conservative
orbital-universe limit; this is not an adopted physical sensor architecture.
The prepared six-host/18-target arrays are a membership-check fixture, not a
full-constellation experiment or a completed ground-network scenario.

Scenario preparation rejects broad cohorts, non-LEO regimes, and non-payload
sensor-host settings under the active policy. Cached arrays are checked against
the pinned IDs before reuse. Scope changes enter the cache key. New campaign,
dropout, and main all-catalogue execution entry points reject orbital-only work
while the active scope requires ground systems. Existing unscoped APIs remain
available in archived workspaces without this active-policy file.

## Ground systems and physical roles

The user has been asked whether ground systems are tracking sensors or
communications gateways, and whether NEXT is a tracked constellation or assumed
sensor-host constellation. These roles require different observation/link
models. No ground stations have silently been fabricated or counted as included.

NEXT orbital positions alone do not justify treating these spacecraft as optical
or radar observers. Aireon's documented hosted payloads receive aircraft ADS-B
signals; their presence does not validate the earlier assumed space-to-space
optical tasking model. See [Aireon's constellation description](https://aireon.com/iridium-constellation/).
The existing ground reference datasets concern other missions and cannot be
relabelled as matched NEXT observations. Integration requires explicit roles,
site coordinates, observation/link assumptions and separate validation.

The current orbital-only campaign runner therefore fails with a clear ground-
system requirement rather than emitting results labelled NEXT plus ground.

## Optional MEO

MEO is disabled. No generic MEO objects, GPS, Galileo or other constellation is
automatically added. A future extension needs a named constellation, explicit
membership, historical elements and a compatible scenario implementation; merely
changing the existing `regime` argument is insufficient. GEO/HEO and other LEO
constellations are outside the requested participant scope.

## Evidence

The shared [scope audit](../reports/evidence/iridium-next-scope/audit.json) independently compares the raw
NEXT list, pinned membership, SATCAT payload types, all historical object IDs,
and every prepared fixture ID. It explicitly records that ground systems and
MEO are not included in those arrays. No new tracking-performance claim follows
from a membership audit.

The focused scope/environment checks passed: 30 tests, two optional skips.
Scope tests include legacy-Iridium rejection, MEO rejection, pin tampering,
cache contamination and the ground-required execution gate.

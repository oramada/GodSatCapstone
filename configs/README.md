# Configurations

- `active-study-scope.json`: enforced participant scope and ground-system requirement.
- `iridium-next-membership.json`: pinned spacecraft IDs from CelesTrak's dedicated NEXT group, including listed spares.
- `iridium-next-ground.json`: current six-ground-site/all-NEXT tracking model; MEO is disabled.
- `ground-tracking-sites.json`: published monument coordinates and velocities for six sites; sensor characteristics are hypothetical.
- `archive/`: earlier mixed-catalogue and hardware-specific configurations. These are historical records, not alternatives that bypass the active scope.

The current config uses the documented ground-tracking sensor model. It does not represent a communications-gateway study or calibrated station operations. See [scope and readiness](../docs/iridium-next-ground-scope.md).

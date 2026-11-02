# Configurations

- `active-study-scope.json`: enforced participant scope and ground-system requirement.
- `iridium-next-membership.json`: pinned spacecraft IDs from CelesTrak's dedicated NEXT group, including listed spares.
- `iridium-next-ground.json`: current default; MEO is disabled and ground-system integration remains pending.
- `archive/`: earlier mixed-catalogue and hardware-specific configurations. These are historical records, not alternatives that bypass the active scope.

The current config supports preparing restricted orbital inputs. It does not by itself implement ground sensors or communications gateways. See [scope and readiness](../docs/iridium-next-ground-scope.md).

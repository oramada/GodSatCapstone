"""Published ground coordinates with explicitly simulated NEXT observations."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np

from .orbits import ROOT, History, utc
from .scope import active_scope, allowed_ids, validate_selected
from .sensorphysics import PhysicalTaskingEnv, slew_profile


def station_positions(sites, times):
    """Propagate the applicable monument solution, without bridging solution gaps."""
    xyz = np.empty((len(times), len(sites), 3))
    for k, instant in enumerate(times):
        for i, site in enumerate(sites):
            active = [s for s in site['solutions']
                      if (s['start'] is None or utc(s['start']) <= instant)
                      and (s['end'] is None or instant <= utc(s['end']))]
            if len(active) != 1:
                raise ValueError(f'No unique dated ground solution: {site["site_id"]} at {instant}')
            solution = active[0]
            years = (instant-utc(solution['reference_epoch'])).total_seconds()/(365.25*86400)
            xyz[k, i] = np.asarray(solution['xyz_m'])+years*np.asarray(solution['velocity_m_per_year'])
    return xyz


def ground_geometry(directions, ranges, finite, up, pointing, config):
    elevation_sine = np.sum(directions*up[:, None, :], axis=-1)
    visible = (finite & (ranges > 1) & (ranges <= config['max_range_km']) &
               (elevation_sine >= np.sin(np.deg2rad(config['ground_min_elevation_deg']))))
    angles = np.arccos(np.clip(np.sum(directions*pointing[:, None, :], axis=-1), -1, 1))
    field = np.arccos(np.clip(elevation_sine, -1, 1)) <= np.deg2rad(config['field_of_regard_deg'])
    duration, _, _ = slew_profile(angles, config['gimbal_inertia_kg_m2'],
                                 config['gimbal_max_torque_nm'], np.deg2rad(config['slew_rate_deg_s']),
                                 config['gimbal_efficiency'])
    return visible, visible & field & (duration <= config['step_seconds']+1e-10), angles


class GroundTrackingEnv(PhysicalTaskingEnv):
    def reset(self):
        self._pointing_index = 0
        super().reset()
        self.pointing = self.s['ground_up'][0].copy()
        return self.observation()

    def geometry(self):
        # An uncommanded mount keeps its Earth-fixed orientation between ticks.
        if self._pointing_index != self.t:
            rotations = self.s['itrs_to_teme']
            change = rotations[self.t] @ rotations[self._pointing_index].T
            self.pointing = self.pointing @ change.T
            self._pointing_index = self.t
        states = self.s['states'][self.t, :, :3]
        delta = states[self.a:][None, :, :]-states[:self.a][:, None, :]
        ranges = np.linalg.norm(delta, axis=-1)
        directions = delta/np.maximum(ranges[:, :, None], 1e-9)
        finite = np.isfinite(directions).all(axis=-1)
        directions, ranges = np.nan_to_num(directions), np.nan_to_num(ranges)
        visible, allowed, angles = ground_geometry(directions, ranges, finite,
                                                   self.s['ground_up'][self.t], self.pointing, self.c)
        return directions, ranges, angles, visible, allowed


def prepare_ground(date, config, root=ROOT):
    from astropy import units as u
    from astropy.coordinates import CartesianRepresentation, EarthLocation, ITRS, TEME
    from astropy.time import Time
    from astropy.utils import iers
    from .scenario import cache_key

    root = Path(root)
    policy = active_scope(root)
    sites_path = root/config['ground_sites']
    raw = sites_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != config['ground_sites_sha256'] or digest != policy['ground_sites_sha256']:
        raise ValueError('Ground sites do not match the pinned scope/configuration')
    sites = json.loads(raw)['sites']
    targets = np.asarray(sorted(allowed_ids(root)), dtype=np.int64)
    if config['agents'] != len(sites) or config['targets'] != len(targets):
        raise ValueError('Ground study must include all configured sites and all pinned NEXT targets')
    folder = root/'data/scenarios'
    folder.mkdir(exist_ok=True, parents=True)
    path = folder/(cache_key(date, config, 'leo', root)+'.npz')
    metadata_path = path.with_suffix('.json')
    if path.exists() and metadata_path.exists():
        with np.load(path, allow_pickle=False) as data:
            validate_selected(data['ids'][len(sites):], root)
            expected_ground = -np.asarray([int(s['site_id']) for s in sites])
            if (not np.array_equal(data['ids'][len(sites):], targets)
                    or not np.array_equal(data['ids'][:len(sites)], expected_ground)
                    or int(data['agents']) != len(sites)
                    or str(data['scenario_kind']) != 'ground_tracks_iridium_next_v1'):
                raise ValueError('Cached ground scenario has incomplete NEXT membership')
        return path
    start = utc(date)
    steps = int(config['duration_minutes']*60/config['step_seconds'])
    times = [start+dt.timedelta(seconds=k*config['step_seconds']) for k in range(steps+1)]
    history = History(root, 'iridium_next')
    try:
        states, ages, errors, epochs = history.replay(targets, times, config['max_element_age_hours'])
    finally:
        history.db.close()
    xyz = station_positions(sites, times)
    location = EarthLocation.from_geocentric(xyz[:,:,0]*u.m, xyz[:,:,1]*u.m, xyz[:,:,2]*u.m)
    lon, lat, _ = location.geodetic
    normal = np.stack([np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)],axis=-1)
    normal = np.asarray(normal)
    ground_states = np.zeros((len(times), len(sites), 6))
    up = np.empty_like(xyz)
    rotations = np.empty((len(times), 3, 3))
    # Frame transform has no refraction/stellar aberration; both endpoints are geocentric.
    with iers.conf.set_temp('auto_download', False):
        for k, instant in enumerate(times):
            at = Time(instant)
            basis = ITRS(CartesianRepresentation(np.eye(3)*u.km), obstime=at).transform_to(TEME(obstime=at))
            rotation = basis.cartesian.xyz.to_value(u.km)
            rotations[k] = rotation
            ground_states[k, :, :3] = xyz[k] @ rotation.T/1000
            up[k] = normal[k] @ rotation.T
        eop = iers.earth_orientation_table.get()
        eop_path = Path(eop.meta.get('data_path', ''))
        eop_hash = hashlib.sha256(eop_path.read_bytes()).hexdigest() if eop_path.is_file() else None
    if not np.allclose(rotations @ rotations.transpose(0, 2, 1), np.eye(3), atol=1e-12):
        raise ValueError('Ground frame transforms are not orthogonal')
    ground_states[:, :, 3:] = np.gradient(ground_states[:, :, :3], config['step_seconds'], axis=0)
    ids = np.r_[-np.asarray([int(s['site_id']) for s in sites]), targets]
    joined = np.concatenate([ground_states, states], axis=1)
    np.savez_compressed(path, states=joined, ages=np.c_[np.zeros((len(times), len(sites))), ages],
                        errors=np.c_[np.zeros((len(times), len(sites)), dtype=errors.dtype), errors],
                        source_epochs=np.c_[np.full((len(times), len(sites)), start.isoformat()), epochs],
                        times=np.asarray([t.isoformat() for t in times]), ids=ids, agents=len(sites),
                        ground_up=up, itrs_to_teme=rotations, ground_itrs_m=xyz,
                        scenario_kind=np.asarray('ground_tracks_iridium_next_v1'))
    metadata = {'date': date, 'scenario_kind': 'ground_tracks_iridium_next_v1', 'frame': 'TEME',
                'ground_systems_included': True, 'ground_site_ids': [s['site_id'] for s in sites],
                'ground_site_names': [s['name'] for s in sites], 'ground_sites_sha256': digest,
                'target_ids': targets.tolist(), 'target_valid_fraction': float(np.isfinite(states[:, :, 0]).mean()),
                'all_pinned_targets_included': True, 'meo_included': False,
                'eop_table': type(eop).__name__, 'eop_data_sha256': eop_hash,
                'limitations': 'Published site coordinates with hypothetical tracking/detection/energy model; not actual NEXT ground measurements. Missing historical targets stay missing; listed spares are included as tracking targets.'}
    metadata_path.write_text(json.dumps(metadata, indent=2)+'\n')
    return path

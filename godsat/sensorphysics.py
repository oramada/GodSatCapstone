"""Opt-in assumed gimbal physics and false-association sensor model.

Parameters are engineering assumptions, not calibration of a particular vehicle.
The legacy environment and its frozen campaigns remain separate estimands.
"""
from __future__ import annotations

import numpy as np

from .environment import TaskingEnv


def slew_profile(angle, inertia, torque, speed, efficiency, drive_power=0.):
    """Minimum-time symmetric rest-to-rest slew; dissipative braking, no regen.

    angle in rad, inertia kg m², torque N m, speed rad/s. Electrical energy
    covers ideal acceleration work / efficiency plus fixed drive electronics
    power during the slew. Holding, bearing friction, vibration and tracking
    energy are excluded.
    """
    angle = np.asarray(angle, dtype=float)
    if (np.any(~np.isfinite(angle)) or np.any(angle < 0) or
            not np.isfinite([inertia, torque, speed, efficiency, drive_power]).all() or
            min(inertia, torque, speed, efficiency) <= 0 or efficiency > 1 or drive_power < 0):
        raise ValueError('Invalid angle or mechanical assumptions')
    acceleration = torque / inertia
    peak = np.minimum(np.sqrt(angle * acceleration), speed)
    duration = np.where(angle <= speed * speed / acceleration,
                        2 * np.sqrt(angle / acceleration),
                        angle / speed + speed / acceleration)
    energy = .5 * inertia * peak * peak / efficiency + drive_power * duration
    return duration, energy, peak


class PhysicalTaskingEnv(TaskingEnv):
    def __init__(self, scenario, config, *args, **kwargs):
        self.inertia = float(config['gimbal_inertia_kg_m2'])
        self.torque = float(config['gimbal_max_torque_nm'])
        self.speed = np.deg2rad(float(config['slew_rate_deg_s']))
        self.efficiency = float(config['gimbal_efficiency'])
        self.drive_power = float(config['gimbal_drive_power_watts'])
        self.clutter_probability = float(config['false_association_probability_per_missed_look'])
        if not 0 <= self.clutter_probability <= 1:
            raise ValueError('False-association probability must be in [0,1]')
        slew_profile(0., self.inertia, self.torque, self.speed, self.efficiency, self.drive_power)
        super().__init__(scenario, config, *args, **kwargs)

    def reset(self):
        result = super().reset()
        self.truth_last_seen = self.last_seen.copy()
        self.latest_report_false = np.zeros(self.k, dtype=bool)
        # Independent stream; no changes to the nominal detection/dropout draws.
        self.clutter_uniforms = np.random.default_rng(
            np.random.SeedSequence([self.seed, 502183])).random((self.steps, self.a, self.k))
        self.physical_energy = []
        self.false_observations = 0
        self.reported_observations = 0
        self.false_track_slots = 0
        self.reported_track_slots = 0
        self._last_failure_total = 0
        return result

    def geometry(self):
        directions, ranges, angles, visible, allowed = super().geometry()
        duration, _, _ = slew_profile(angles, self.inertia, self.torque, self.speed, self.efficiency)
        return directions, ranges, angles, visible, allowed & (duration <= self.dt + 1e-10)

    def step(self, actions):
        time_index = self.t
        reported_seen = self.last_seen.copy()
        _, _, angles, _, _ = self.geometry()
        # Ground truth is used for the training response, never as an observed
        # correction to the reported track-age feature seen by the policy.
        self.last_seen = self.truth_last_seen.copy()
        _, _, done = super().step(actions)
        self.truth_last_seen = self.last_seen.copy()
        true_observations = np.asarray(self.trace[-1]['detected'], dtype=int)
        false_observations = []
        joules = np.zeros(self.a)
        for i,j in np.argwhere(self.previous_claims):
            _, joules[i], _ = slew_profile(angles[i,j], self.inertia, self.torque, self.speed, self.efficiency, self.drive_power)
            dropped = (bool(self.dropout_state[i]) if self.dropout_mode == 'burst'
                       else self.dropout_uniforms[time_index,i,j] < self.dropout_probability)
            if (j not in true_observations and not dropped and
                    self.clutter_uniforms[time_index,i,j] < self.clutter_probability):
                false_observations.append(int(j))
        now = time_index * self.dt
        reported_seen[true_observations] = now
        reported_seen[false_observations] = now
        self.latest_report_false[true_observations] = False
        self.latest_report_false[false_observations] = True
        self.last_seen = reported_seen
        valid = np.isfinite(self.s['states'][time_index,self.a:,0])
        active = valid & ((now - reported_seen) <= self.c['custody_seconds'])
        false_active = active & self.latest_report_false
        self.false_track_slots += int(false_active.sum())
        self.reported_track_slots += int(active.sum())
        self.false_observations += len(false_observations)
        self.reported_observations += len(true_observations) + len(false_observations)
        self.physical_energy.append(float(joules.mean()))
        reference = .5 * self.inertia * self.speed**2 / self.efficiency + self.drive_power * self.dt
        previous_reward = self.trace[-1]['reward']
        # Replace the legacy squared-angle and miss penalty by physical slew
        # energy and active false-track penalties. Retain custody and conflicts.
        legacy_slew = self.trace[-1]['slew_proxy']
        false_fraction = float(false_active.sum() / max(active.sum(), 1))
        previous_failures = (self.failures - getattr(self, '_last_failure_total', 0))
        self._last_failure_total = self.failures
        reward = (previous_reward + self.c['slew_penalty'] * legacy_slew
                  + self.c['false_penalty'] * previous_failures / self.a
                  - self.c['slew_penalty'] * joules.mean() / reference
                  - self.c['false_penalty'] * false_fraction)
        self.trace[-1].update(reward=float(reward), slew_energy_joules_mean=float(joules.mean()),
                              false_observations=false_observations,
                              active_false_tracks=int(false_active.sum()), active_reported_tracks=int(active.sum()))
        return self.observation(), float(reward), done

    def metrics(self):
        return {**super().metrics(),
                'slew_energy_joules': float(np.mean(self.physical_energy)),
                'total_slew_energy_joules': float(np.sum(self.physical_energy) * self.a),
                'false_track_rate': self.false_track_slots / max(self.reported_track_slots, 1),
                'false_observation_rate': self.false_observations / max(self.reported_observations, 1),
                'false_track_slots': self.false_track_slots,
                'reported_track_slots': self.reported_track_slots,
                'false_observations': self.false_observations,
                'reported_observations': self.reported_observations}


def environment_class(config):
    model = config.get('sensor_response_model', 'legacy_proxy')
    if model == 'legacy_proxy':
        return TaskingEnv
    if model == 'assumed_gimbal_and_clutter_v1':
        return PhysicalTaskingEnv
    if model == 'ground_tracking_gimbal_and_clutter_v1':
        from .ground import GroundTrackingEnv
        return GroundTrackingEnv
    raise ValueError(f'Unknown sensor_response_model: {model}')

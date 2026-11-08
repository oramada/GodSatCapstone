"""Vectorized force terms in km/s units, with no inferred spacecraft properties.

References: IERS Conventions 2010 §10.3 (Schwarzschild); Montenbruck & Gill,
Satellite Orbits §3.2 and §3.4 (zonal potential and cannonball SRP). Eclipse
uses overlapping apparent circular solar/Earth discs, a spherical occultor,
and uniform solar radiance. No atmosphere, lunar shadow or limb darkening.
"""
import numpy as np

C_KM_S = 299792.458
AU_KM = 149597870.7
SUN_RADIUS_KM = 695700.0
SOLAR_PRESSURE_N_M2 = 4.56e-6


def vectors(value, name):
    array = np.asarray(value, dtype=float)
    if array.ndim != 2 or array.shape[1] != 3 or not np.isfinite(array).all():
        raise ValueError(f'{name} requires finite N×3 vectors')
    return array


def zonal_gravity(position, mu, radius, coefficients):
    """Gradient of U=mu/r [1-sum Jn (R/r)^n Pn(z/r)], including monopole.

    The Jn are *unnormalized*, with Jn=-sqrt(2n+1)*Cbar(n,0).
    Evaluate in Earth-fixed axes. Recurrence derivatives are finite at poles.
    """
    position = vectors(position, 'Gravity position')
    r = np.linalg.norm(position, axis=1)
    if not np.isfinite(mu) or mu <= 0 or not np.isfinite(radius) or radius <= 0 or np.any(r <= radius):
        raise ValueError('Gravity requires positive constants and positions outside the reference sphere')
    unit = position / r[:, None]
    s = unit[:, 2]
    acceleration = -mu / r[:, None]**2 * unit
    p0, p1 = np.ones_like(s), s.copy()
    d0, d1 = np.zeros_like(s), np.ones_like(s)
    values = {int(k): float(v) for k, v in coefficients.items()}
    if any(n < 2 or n > 8 or not np.isfinite(v) for n, v in values.items()):
        raise ValueError('Zonal degrees must be 2–8 with finite coefficients')
    for n in range(2, max(values, default=1) + 1):
        pn = ((2*n-1)*s*p1 - (n-1)*p0)/n
        dn = ((2*n-1)*(p1+s*d1) - (n-1)*d0)/n
        if n in values:
            factor = mu/r**2 * values[n]*(radius/r)**n
            term = ((n+1)*pn+s*dn)[:, None]*unit
            term[:, 2] -= dn
            acceleration += factor[:, None]*term
        p0, p1, d0, d1 = p1, pn, d1, dn
    return acceleration


def illumination_fraction(position, sun, earth_radius_km, sun_radius_km=SUN_RADIUS_KM):
    """Sunlit area fraction from angular-disc overlap, in [0,1]."""
    position = vectors(position, 'Eclipse position')
    sun = np.asarray(sun, dtype=float)
    if sun.shape != (3,) or not np.isfinite(sun).all():
        raise ValueError('Sun requires a finite geocentric three-vector')
    to_sun = sun-position
    r = np.linalg.norm(position, axis=1)
    distance = np.linalg.norm(to_sun, axis=1)
    if not np.isfinite(earth_radius_km) or not np.isfinite(sun_radius_km) or earth_radius_km <= 0 or sun_radius_km <= 0 or np.any(r <= earth_radius_km) or np.any(distance <= sun_radius_km):
        raise ValueError('Eclipse geometry must be outside Earth and Sun')
    a = np.arcsin(sun_radius_km/distance)
    b = np.arcsin(earth_radius_km/r)
    earth_direction = -position/r[:, None]
    sun_direction = to_sun/distance[:, None]
    separation = np.arctan2(np.linalg.norm(np.cross(earth_direction, sun_direction), axis=1),
                            np.sum(earth_direction*sun_direction, axis=1))
    result = np.ones(len(position))
    contained = separation <= np.abs(a-b)
    result[contained] = 1 - np.minimum(a[contained], b[contained])**2/a[contained]**2
    overlap = (~contained) & (separation < a+b)
    if np.any(overlap):
        x,y,d = a[overlap],b[overlap],separation[overlap]
        area = x*x*np.arccos(np.clip((d*d+x*x-y*y)/(2*d*x),-1,1))
        area += y*y*np.arccos(np.clip((d*d+y*y-x*x)/(2*d*y),-1,1))
        area -= .5*np.sqrt(np.maximum(0,(-d+x+y)*(d+x-y)*(d-x+y)*(d+x+y)))
        result[overlap] = 1-area/(np.pi*x*x)
    return np.clip(result,0,1)


def solar_radiation_acceleration(position, sun, cr_area_mass, earth_radius_km):
    """Cannonball acceleration away from Sun; Cr*A/m is explicit in m²/kg."""
    position = vectors(position, 'Radiation position')
    susceptibility = np.asarray(cr_area_mass, dtype=float)
    if susceptibility.shape != (len(position),) or not np.isfinite(susceptibility).all() or np.any(susceptibility < 0):
        raise ValueError('Radiation susceptibility requires one nonnegative value per object')
    lit = illumination_fraction(position, sun, earth_radius_km)
    away = position - np.asarray(sun)
    distance = np.linalg.norm(away, axis=1)
    # N/kg = m/s²; convert to km/s² exactly once.
    scale = SOLAR_PRESSURE_N_M2/1000*(AU_KM/distance)**2*susceptibility*lit
    return away/distance[:, None]*scale[:, None], lit


def schwarzschild_acceleration(position, velocity, mu):
    """IERS 2010 Eq 10.12 first line, beta=gamma=1, in geocentric axes.

    This is only the leading spherical correction, not full relativistic dynamics.
    """
    position, velocity = vectors(position, 'Relativity position'), vectors(velocity, 'Relativity velocity')
    r = np.linalg.norm(position, axis=1)
    if position.shape != velocity.shape or np.any(r == 0) or not np.isfinite(mu) or mu <= 0:
        raise ValueError('Relativity requires matching vectors, positive radius and mu')
    speed2 = np.sum(velocity*velocity, axis=1)
    rv = np.sum(position*velocity, axis=1)
    return (mu/(C_KM_S**2*r**3))[:, None]*((4*mu/r-speed2)[:, None]*position+4*rv[:, None]*velocity)

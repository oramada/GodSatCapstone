//! CPU scene evaluation shared by native tests and the browser's WebAssembly core.
//! No rendering, ephemeris or detector model is hidden in this module.
//!
//! The C ABI accepts only buffers allocated by the matching alloc_* functions.
//! All lengths and pointers must agree with the packed scene dimensions.
use std::slice;

pub const UNAVAILABLE: f64 = 0.;
pub const UNKNOWN: f64 = 1.;
pub const OBSERVED: f64 = 2.;
pub const STALE: f64 = 3.;
pub const LOST: f64 = 4.;

#[no_mangle]
pub extern "C" fn alloc_f64(len: usize) -> *mut f64 {
    Box::into_raw(vec![0.; len].into_boxed_slice()) as *mut f64
}
#[no_mangle]
pub extern "C" fn alloc_u8(len: usize) -> *mut u8 {
    Box::into_raw(vec![0u8; len].into_boxed_slice()) as *mut u8
}
#[no_mangle]
pub extern "C" fn alloc_i32(len: usize) -> *mut i32 {
    Box::into_raw(vec![-1; len].into_boxed_slice()) as *mut i32
}
/// # Safety
/// Pointer and length must match a live allocation returned by alloc_f64.
#[no_mangle]
pub unsafe extern "C" fn free_f64(ptr: *mut f64, len: usize) {
    drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(ptr, len)));
}
/// # Safety
/// Pointer and length must match a live allocation returned by alloc_u8.
#[no_mangle]
pub unsafe extern "C" fn free_u8(ptr: *mut u8, len: usize) {
    drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(ptr, len)));
}
/// # Safety
/// Pointer and length must match a live allocation returned by alloc_i32.
#[no_mangle]
pub unsafe extern "C" fn free_i32(ptr: *mut i32, len: usize) {
    drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(ptr, len)));
}

pub fn last_seen(observations: &[u8], frames: usize, objects: usize, history: &mut [i32]) {
    for j in 0..objects {
        let mut last = -1;
        for k in 0..frames {
            let offset = k * objects + j;
            if observations[offset] == 2 {
                last = k as i32;
            }
            history[offset] = last;
        }
    }
}

/// Evaluate all objects in one call. Output stride is six f64s:
/// [x_km, y_km, z_km, state_code, last_seen_frame, age_seconds].
/// NaN positions mean an unavailable interpolation interval, never an origin.
pub fn frame(
    positions: &[f64],
    times: &[f64],
    observations: &[u8],
    history: &[i32],
    objects: usize,
    step: f64,
    custody: f64,
    out: &mut [f64],
) {
    if times.is_empty() {
        return;
    }
    let step = step.max(0.).min((times.len() - 1) as f64);
    let a = step.floor() as usize;
    let b = (a + 1).min(times.len() - 1);
    let alpha = step - a as f64;
    for j in 0..objects {
        let oi = j * 6;
        let pa = (a * objects + j) * 3;
        let pb = (b * objects + j) * 3;
        let valid = positions[pa..pa + 3].iter().all(|v| v.is_finite());
        let interpolable = valid && positions[pb..pb + 3].iter().all(|v| v.is_finite());
        for axis in 0..3 {
            out[oi + axis] = if interpolable {
                positions[pa + axis] + (positions[pb + axis] - positions[pa + axis]) * alpha
            } else {
                f64::NAN
            };
        }
        let last = history[a * objects + j];
        let (state, seen, age) = if !valid {
            (UNAVAILABLE, -1., f64::NAN)
        } else if observations[a * objects + j] == 0 {
            (UNKNOWN, -1., f64::NAN)
        } else if last < 0 {
            (LOST, -1., f64::NAN)
        } else {
            let age = (times[a] - times[last as usize]) / 1000.;
            (
                if age == 0. {
                    OBSERVED
                } else if age <= custody {
                    STALE
                } else {
                    LOST
                },
                last as f64,
                age,
            )
        };
        out[oi + 3] = state;
        out[oi + 4] = seen;
        out[oi + 5] = age;
    }
}

/// # Safety
/// observation/history buffers must contain frames*objects elements, be valid,
/// non-overlapping, and history must be writable.
#[no_mangle]
pub unsafe extern "C" fn prepare(
    observations: *const u8,
    history: *mut i32,
    frames: usize,
    objects: usize,
) {
    last_seen(
        slice::from_raw_parts(observations, frames * objects),
        frames,
        objects,
        slice::from_raw_parts_mut(history, frames * objects),
    );
}
/// # Safety
/// All buffers must be valid, correctly sized, non-overlapping allocations.
/// Positions length = frames*objects*3; times = frames; observations/history =
/// frames*objects; output = objects*6. The JS bridge bounds scene dimensions.
#[no_mangle]
pub unsafe extern "C" fn evaluate(
    positions: *const f64,
    times: *const f64,
    observations: *const u8,
    history: *const i32,
    frames: usize,
    objects: usize,
    step: f64,
    custody: f64,
    out: *mut f64,
) {
    frame(
        slice::from_raw_parts(positions, frames * objects * 3),
        slice::from_raw_parts(times, frames),
        slice::from_raw_parts(observations, frames * objects),
        slice::from_raw_parts(history, frames * objects),
        objects,
        step,
        custody,
        slice::from_raw_parts_mut(out, objects * 6),
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn expiry_boundary_reacquisition_and_gap() {
        let times: Vec<f64> = (0..7).map(|i| i as f64 * 60000.).collect();
        let obs = [2, 1, 1, 1, 1, 0, 2];
        let mut history = [-1; 7];
        last_seen(&obs, 7, 1, &mut history);
        let mut positions = vec![7000.; 21];
        let mut out = [0.; 6];
        for (step, state) in [
            (0., OBSERVED),
            (3., STALE),
            (4., LOST),
            (5., UNKNOWN),
            (6., OBSERVED),
        ] {
            frame(&positions, &times, &obs, &history, 1, step, 180., &mut out);
            assert_eq!(out[3], state);
        }
        positions[3] = f64::NAN;
        frame(&positions, &times, &obs, &history, 1, 0.5, 180., &mut out);
        assert!(out[0].is_nan());
        frame(&positions, &times, &obs, &history, 1, 1., 180., &mut out);
        assert_eq!(out[3], UNAVAILABLE);
    }
    #[test]
    fn interpolation_and_independent_histories() {
        let positions = [1., 2., 3., 10., 20., 30., 3., 4., 5., 30., 40., 50.];
        let times = [0., 60000.];
        let obs = [2, 1, 1, 2];
        let mut history = [-1; 4];
        let mut out = [0.; 12];
        last_seen(&obs, 2, 2, &mut history);
        frame(&positions, &times, &obs, &history, 2, 0.5, 180., &mut out);
        assert_eq!(&out[..3], &[2., 3., 4.]);
        assert_eq!(&out[6..9], &[20., 30., 40.]);
        assert_eq!(out[3], OBSERVED);
        assert_eq!(out[9], LOST);
    }
}

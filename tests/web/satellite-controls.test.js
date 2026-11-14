import assert from 'node:assert/strict';
import test from 'node:test';
import { satellitesInBox } from '../../web/studio/satellite-controls.js';

test('box picking selects projected visible satellites and favors the center', () => {
  class Vector {
    static subtract(a, b, result) { result.z = a.z - b.z; }
    static dot(a, b) { return a.z * b.z; }
  }
  const C = {
    Cartesian2: Vector,
    Cartesian3: Vector,
    Ellipsoid: { WGS84: {} },
    EllipsoidalOccluder: class {
      isPointVisible(position) { return !position.occluded; }
    },
    SceneTransforms: { worldToWindowCoordinates: (_, position) => position },
  };
  const scene = { globe: { show: true }, camera: { positionWC: { z: 0 }, directionWC: { z: 1 } } };
  const item = (id, x, y, { kind, show = true, z = 1, occluded = false } = {}) => ({
    object: { id, kind },
    point: { show, position: { x, y, z, occluded } },
  });
  const items = [
    item('corner', 10, 10),
    item('center', 20, 20),
    item('offscreen', 35, 20),
    item('station', 20, 20, { kind: 'station' }),
    item('behind camera', 20, 20, { z: -1 }),
    item('behind Earth', 20, 20, { occluded: true }),
    item('hidden', 20, 20, { show: false }),
  ];
  assert.deepEqual(satellitesInBox(C, scene, items, { left: 10, right: 30, top: 10, bottom: 30 }), {
    matches: ['corner', 'center'], closest: 'center',
  });
});

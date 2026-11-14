import assert from 'node:assert/strict';
import test from 'node:test';
import {FreeCamera} from '../../web/studio/camera.js';

test('free flight moves while keys are held and restores orbit controls', () => {
  const saved = { enableRotate: true, enableTranslate: true, enableTilt: true, enableZoom: true, enableLook: true, lookEventTypes: { modifier: 'shift' } };
  const controller = { ...saved };
  const container = new EventTarget();
  const moves = [];
  const angles = [];
  let draws = 0;
  let focused = false;
  container.focus = () => { focused = true; };
  globalThis.window = new EventTarget();
  globalThis.document = new EventTarget();
  const controls = new FreeCamera(container, {
    screenSpaceCameraController: controller,
    camera: { positionCartographic: { height: 1000 }, moveForward: distance => moves.push(distance), twistLeft: angle => angles.push(angle) },
    requestRender() { draws++; },
  }, 'left-drag');

  const key = (target, type, shiftKey = false, code = 'KeyW') => {
    const event = Object.assign(new Event(type, { cancelable: true }), { code, shiftKey });
    target.dispatchEvent(event);
    return event.defaultPrevented;
  };

  try {
    assert.equal(key(container, 'keydown'), false);
    controls.setMode('free');
    assert.equal(controller.lookEventTypes, 'left-drag');
    assert.equal(controller.enableRotate, false);
    container.dispatchEvent(new Event('pointerdown'));
    assert.equal(focused, true);
    assert.equal(key(container, 'keydown'), true);
    controls.update(performance.now() + 100);
    assert.deepEqual(moves, [50]);
    key(window, 'keyup');
    controls.update(performance.now() + 200);
    assert.equal(draws, 1);
    key(container, 'keydown', true);
    assert.equal(key(container, 'keydown', true, 'KeyZ'), true);
    controls.update(performance.now() + 100);
    assert.deepEqual(moves, [50, 200]);
    assert.deepEqual(angles, [Math.PI / 40]);
    container.dispatchEvent(new Event('blur'));
    controls.update(performance.now() + 200);
    assert.equal(draws, 2);
    controls.setMode('orbit');
    assert.deepEqual(controller, saved);
  } finally {
    controls.destroy();
    delete globalThis.window;
    delete globalThis.document;
  }
});

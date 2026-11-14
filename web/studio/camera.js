const MOVEMENT = {
  KeyW: 'moveForward',
  KeyS: 'moveBackward',
  KeyA: 'moveLeft',
  KeyD: 'moveRight',
  KeyQ: 'moveDown',
  KeyE: 'moveUp',
};

const ROTATION = {
  ArrowLeft: 'lookLeft',
  ArrowRight: 'lookRight',
  ArrowUp: 'lookUp',
  ArrowDown: 'lookDown',
  KeyZ: 'twistLeft',
  KeyC: 'twistRight',
};

export class FreeCamera {
  constructor(container, scene, leftDrag) {
    this.scene = scene;
    this.controller = scene.screenSpaceCameraController;
    this.leftDrag = leftDrag;
    this.keys = new Set();
    this.listeners = new AbortController();
    const options = { signal: this.listeners.signal };
    const clear = () => this.keys.clear();

    container.addEventListener('pointerdown', () => {
      if (this.orbitControls) container.focus({ preventScroll: true });
    }, options);
    container.addEventListener('keydown', event => {
      if (!this.orbitControls || event.ctrlKey || event.metaKey || event.altKey) return;
      if (!Object.hasOwn(MOVEMENT, event.code) && !Object.hasOwn(ROTATION, event.code)) return;
      event.preventDefault();
      if (!this.keys.size) this.lastTick = performance.now();
      this.keys.add(event.code);
      this.fast = event.shiftKey;
    }, options);
    window.addEventListener('keyup', event => {
      this.keys.delete(event.code);
      this.fast = event.shiftKey;
    }, options);
    window.addEventListener('keydown', event => {
      if (this.keys.size) this.fast = event.shiftKey;
    }, options);
    container.addEventListener('blur', clear, options);
    window.addEventListener('blur', clear, options);
    document.addEventListener('visibilitychange', clear, options);
  }

  setMode(mode) {
    if (mode === 'free' && !this.orbitControls) {
      const overrides = {
        enableRotate: false,
        enableTranslate: false,
        enableTilt: false,
        enableZoom: false,
        enableLook: true,
        lookEventTypes: this.leftDrag,
      };
      this.orbitControls = Object.fromEntries(Object.keys(overrides).map(key => [key, this.controller[key]]));
      Object.assign(this.controller, overrides);
    } else if (mode === 'orbit' && this.orbitControls) {
      Object.assign(this.controller, this.orbitControls);
      this.orbitControls = null;
      this.keys.clear();
    }
  }

  update(now) {
    if (!this.keys.size) return;
    const elapsed = Math.min((now - this.lastTick) / 1000, 0.05);
    this.lastTick = now;
    const camera = this.scene.camera;
    const height = Math.abs(camera.positionCartographic.height);
    const speed = Math.max(1000, Math.min(50e6, height * 0.35));
    const movement = [...this.keys].filter(key => Object.hasOwn(MOVEMENT, key));
    const distance = speed * elapsed * (this.fast ? 4 : 1) / Math.sqrt(movement.length || 1);
    for (const key of movement) camera[MOVEMENT[key]](distance);
    for (const key of this.keys) {
      if (Object.hasOwn(ROTATION, key)) camera[ROTATION[key]](elapsed * Math.PI / 2);
    }
    this.scene.requestRender();
  }

  destroy() {
    this.setMode('orbit');
    this.listeners.abort();
  }
}

export function pointAtSun(C, scene, time) {
  // Match Cesium's Sun renderer at the current playback epoch.
  const frame = C.CelestialFrameTransforms.computeIcrfToCentralBodyFixedMatrix(time);
  const sun = C.Simon1994PlanetaryPositions.computeSunPositionInEarthInertialFrame(time);
  C.Matrix3.multiplyByVector(frame, sun, sun);
  const direction = C.Cartesian3.normalize(sun, new C.Cartesian3());
  // Start on the day side so Earth never blocks the Sun.
  const destination = C.Cartesian3.multiplyByScalar(direction, C.Ellipsoid.WGS84.maximumRadius * 3.9, new C.Cartesian3());
  const up = Math.abs(direction.z) < 0.99 ? C.Cartesian3.UNIT_Z : C.Cartesian3.UNIT_Y;
  scene.camera.setView({ destination, orientation: { direction, up } });
  scene.requestRender();
}

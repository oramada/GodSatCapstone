export function satellitesInBox(C, scene, items, box) {
  const camera = scene.camera;
  const occluder = scene.globe.show ? new C.EllipsoidalOccluder(C.Ellipsoid.WGS84, camera.positionWC) : null;
  const offset = new C.Cartesian3();
  const screen = new C.Cartesian2();
  const centerX = (box.left + box.right) / 2;
  const centerY = (box.top + box.bottom) / 2;
  const matches = [];
  let closest;
  let closestDistance = Infinity;
  for (const { object, point } of items) {
    if (!point.show || object.kind === 'station' || object.kind === 'sensor') continue;
    const position = point.position;
    C.Cartesian3.subtract(position, camera.positionWC, offset);
    if (C.Cartesian3.dot(offset, camera.directionWC) <= 0) continue;
    const pixel = C.SceneTransforms.worldToWindowCoordinates(scene, position, screen);
    if (!pixel || pixel.x < box.left || pixel.x > box.right || pixel.y < box.top || pixel.y > box.bottom) continue;
    if (occluder && !occluder.isPointVisible(position)) continue;
    matches.push(object.id);
    const distance = (pixel.x - centerX) ** 2 + (pixel.y - centerY) ** 2;
    if (distance < closestDistance) {
      closest = object.id;
      closestDistance = distance;
    }
  }
  return { matches, closest };
}

export class SatelliteSelection {
  constructor(C, container, scene, select) {
    this.listeners = new AbortController();
    const options = { capture: true, signal: this.listeners.signal };
    const canvas = scene.canvas;
    const rectangle = document.createElement('div');
    rectangle.className = 'studio-selection-box';
    rectangle.hidden = true;
    container.append(rectangle);
    this.rectangle = rectangle;
    const coordinates = event => {
      const bounds = canvas.getBoundingClientRect();
      return {
        x: Math.max(0, Math.min(bounds.width, event.clientX - bounds.left)),
        y: Math.max(0, Math.min(bounds.height, event.clientY - bounds.top)),
      };
    };
    const boundsFor = event => {
      const end = coordinates(event);
      return {
        left: Math.min(this.start.x, end.x), right: Math.max(this.start.x, end.x),
        top: Math.min(this.start.y, end.y), bottom: Math.max(this.start.y, end.y),
      };
    };
    const cancel = () => {
      if (!this.start) return;
      const { id } = this.start;
      this.start = null;
      rectangle.hidden = true;
      if (canvas.hasPointerCapture(id)) canvas.releasePointerCapture(id);
    };
    this.cancel = cancel;
    canvas.addEventListener('pointerdown', event => {
      if ((!this.enabled && !event.shiftKey) || event.button !== 0 || !event.isPrimary) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      this.start = { ...coordinates(event), id: event.pointerId };
      canvas.setPointerCapture(event.pointerId);
    }, options);
    canvas.addEventListener('pointermove', event => {
      if (this.start?.id !== event.pointerId) return;
      event.stopImmediatePropagation();
      const { left, right, top, bottom } = boundsFor(event);
      rectangle.hidden = false;
      Object.assign(rectangle.style, { left: `${left}px`, top: `${top}px`, width: `${right-left}px`, height: `${bottom-top}px` });
    }, options);
    canvas.addEventListener('pointerup', event => {
      if (this.start?.id !== event.pointerId) return;
      event.stopImmediatePropagation();
      const bounds = boundsFor(event);
      cancel();
      if (bounds.right - bounds.left >= 4 && bounds.bottom - bounds.top >= 4) select(bounds);
    }, options);
    for (const type of ['pointercancel', 'lostpointercapture']) canvas.addEventListener(type, cancel, options);
    window.addEventListener('blur', cancel, options);
    window.addEventListener('keydown', event => { if (event.key === 'Escape') cancel(); }, options);
  }

  destroy() {
    this.cancel();
    this.listeners.abort();
    this.rectangle.remove();
  }
}

export class SatelliteCamera {
  constructor(C, scene) {
    this.C = C;
    this.scene = scene;
    this.listeners = new AbortController();
    scene.canvas.addEventListener('wheel', event => {
      if (!this.offset) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 400 : 1);
      this.zoom(Math.exp(Math.max(-1, Math.min(1, pixels * 0.002))));
    }, { capture: true, passive: false, signal: this.listeners.signal });
  }

  follow(position) {
    const { C, scene } = this;
    const controls = scene.screenSpaceCameraController;
    if (!this.offset) {
      this.orbitLook = controls.enableLook;
      controls.enableLook = false;
      this.offset = new C.Cartesian3();
    }
    this.frame = C.Transforms.eastNorthUpToFixedFrame(position, undefined, this.frame);
    scene.camera.lookAtTransform(this.frame, new C.HeadingPitchRange(0, -Math.PI / 3, 160));
    scene.requestRender();
  }

  update(position) {
    if (!this.offset || !position) return;
    const { C, scene } = this;
    C.Cartesian3.clone(scene.camera.position, this.offset);
    C.Transforms.eastNorthUpToFixedFrame(position, undefined, this.frame);
    scene.camera.lookAtTransform(this.frame, this.offset);
  }

  zoom(factor) {
    if (!this.offset) return;
    const { C, scene } = this;
    const range = C.Cartesian3.magnitude(scene.camera.position);
    if (!range) return;
    const distance = Math.max(64, Math.min(8e6, range * factor));
    C.Cartesian3.multiplyByScalar(scene.camera.position, distance / range, this.offset);
    scene.camera.lookAtTransform(this.frame, this.offset);
    scene.requestRender();
  }

  stop() {
    if (!this.offset) return;
    this.scene.screenSpaceCameraController.enableLook = this.orbitLook;
    this.scene.camera.lookAtTransform(this.C.Matrix4.IDENTITY);
    this.offset = null;
    this.scene.requestRender();
  }

  destroy() {
    this.listeners.abort();
  }
}

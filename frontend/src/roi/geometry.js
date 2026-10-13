/**
 * Pure normalised-space geometry for the ROI canvas (plan A12, design §5).
 * Everything works in 0..1 so an ROI drawn at 1080p still means the same
 * wall at 720p; pixel helpers exist only for display and the min-area floor.
 * Containment is edge-inclusive, matching backend `services/alerts/roi.py`.
 */

const EPS = 1e-9;

/**
 * Normalised point → frame pixels.
 * @param {number[]} pt [x, y] in 0..1
 * @param {number} w frame width in pixels
 * @param {number} h frame height in pixels
 * @returns {number[]} [px, py] clamped to the frame
 */
export function toPixels(pt, w, h) {
  const x = Math.min(1, Math.max(0, pt[0])) * w;
  const y = Math.min(1, Math.max(0, pt[1])) * h;
  return [x, y];
}

/**
 * Frame pixels → normalised point, clamped to [0,1].
 * @param {number[]} px [px, py] pixel coordinates
 * @param {number} w frame width in pixels
 * @param {number} h frame height in pixels
 * @returns {number[]} [x, y] in 0..1
 */
export function fromPixels(px, w, h) {
  const x = Math.min(1, Math.max(0, px[0] / w));
  const y = Math.min(1, Math.max(0, px[1] / h));
  return [x, y];
}

/**
 * Polygon area as a percentage of the unit frame (shoelace).
 * @param {number[][]} points normalised vertices, ≥3 for a non-zero result
 * @returns {number} 0..100 (one decimal at most)
 */
export function coveragePct(points) {
  if (!points || points.length < 3) return 0;
  let area = 0;
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % n];
    area += x1 * y2 - x2 * y1;
  }
  return Math.round((Math.abs(area) / 2) * 1000) / 10;
}

/**
 * Polygon area in source-frame pixels — feeds the 500px² floor (design §5.5).
 * @param {number[][]} points normalised vertices
 * @param {number} w frame width
 * @param {number} h frame height
 * @returns {number} area in px²
 */
export function minAreaPx(points, w, h) {
  if (!points || points.length < 3) return 0;
  let area = 0;
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % n];
    area += x1 * y2 - x2 * y1;
  }
  return (Math.abs(area) / 2) * w * h;
}

/**
 * True when (px, py) lies on segment a-b within EPS.
 * @param {number} px point x
 * @param {number} py point y
 * @param {number} ax segment start x
 * @param {number} ay segment start y
 * @param {number} bx segment end x
 * @param {number} by segment end y
 * @returns {boolean} collinear-and-between
 */
function onSegment(px, py, ax, ay, bx, by) {
  const cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax);
  if (Math.abs(cross) > EPS) return false;
  return (
    Math.min(ax, bx) - EPS <= px &&
    px <= Math.max(ax, bx) + EPS &&
    Math.min(ay, by) - EPS <= py &&
    py <= Math.max(ay, by) + EPS
  );
}

/**
 * Edge-inclusive containment by ray casting — mirrors the backend exactly
 * so a centroid on the boundary is judged the same on both sides.
 * @param {number[]} point [x, y] in 0..1
 * @param {number[][]} points polygon vertices, ≥3 required
 * @returns {boolean} whether the point is inside or on the boundary
 */
export function pointInPolygon(point, points) {
  if (!points || points.length < 3) return false;
  const [px, py] = point;
  let inside = false;
  for (let i = 0; i < points.length; i++) {
    const [ax, ay] = points[i];
    const [bx, by] = points[(i + 1) % points.length];
    if (onSegment(px, py, ax, ay, bx, by)) return true;
    if (ay > py !== by > py) {
      const xIntersect = ((bx - ax) * (py - ay)) / (by - ay) + ax;
      if (px < xIntersect) inside = !inside;
    }
  }
  return inside;
}

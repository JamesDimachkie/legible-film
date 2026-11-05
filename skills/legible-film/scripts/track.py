#!/usr/bin/env python3
"""Track a flat surface (a screen, a sign, a product face) or a single point through a source, as a track layer.

  python track.py SOURCE --at TIME --region x,y,w,h --name screen [--from T1 --to T2] [--project PROJECT | --out DIR]
  python track.py SOURCE --at TIME --region x1,y1,x2,y2,x3,y3,x4,y4 --name sign --project PROJECT
  python track.py SOURCE --at TIME --point x,y --name plate --project PROJECT

SOURCE is a file, or a source alias with --project. TIME, T1 and T2 are source times (m:ss.ss or seconds); the range
defaults to 5 s either side of TIME. --region gives the surface at TIME as a box (x, y, width, height) or as four
corners (top-left, top-right, bottom-right, bottom-left), in pixels of the displayed frame (after rotation and pixel
aspect, as frame_sheet.py shows it) or as fractions of it when every value is between 0 and 1. --point follows one
point that only moves (no turn or scale), for a label or a blur that follows something.

Frames are decoded by FFmpeg exactly as assemble.py decodes them (the displayed, autorotated, square-pixel frame and
the same presentation clock), never by OpenCV's own reader, which ignores rotation. Each frame is spooled once to a
temporary file, so memory stays bounded. From the key frame the region is tracked forward to T2 and backward to T1:
features inside it (Shi-Tomasi corners) are followed with pyramidal Lucas-Kanade flow, kept only when tracking them
back lands within a pixel of where they started (forward-backward check), and fitted with a RANSAC homography from
the key frame; new features are found when they thin out. A frame is marked lost, with no corners, when too few
features agree, the fitted region is implausible, or the picture inside it no longer looks like the key frame's
(normalised correlation): the surface left the frame or something covers it. After a loss the key frame's SIFT
features are matched against each frame until the surface is found again, and a surface found again must look more
like the key frame than one followed frame to frame. Every fit is refined against the key frame itself (the frame is
warped back into the key frame's geometry and the small remaining motion measured), so errors do not accumulate.
A track never crosses a shot change: the decode finds cuts (a large picture change well above the recent motion) and
frames in other shots are lost, because a look-alike surface in the next shot is the commonest false match. A point
track compares its patch with its last good look (a face turns, a plate tilts) and, after a loss, searches for it
near its last place.

The layer (spatial/NAME.json in the project, or NAME.json in --out) records each frame's corners (or point) as
fractions of the displayed frame, its state (key, tracked, lost) and error_px: the larger of the homography's RMS
residual and the median forward-backward error of the features it kept, in displayed pixels. Its quality block
gives frames tracked and lost, the median and worst error, and drift: the region tracked from each end of the range
back to the key frame, as the mean distance of its corners from where they started there.

What this does not prove: that the region is the surface you meant, or that a corner pin will look attached; a
surface that bends, reflects or is mostly featureless tracks poorly, and error_px measures agreement between
features, not the true position. Look at frames (frame_sheet.py) of a render that uses it. Needs OpenCV
(setup.py --install spatial), numpy and FFmpeg. Exit codes: 0 every frame tracked; 1 some frames lost or the error is
large (inspect them); 2 could not run (OpenCV missing, a bad region, a source that cannot be read).
"""
import argparse
import importlib.util
import math
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_sibling(name):
    """Load a sibling script as a module, the way the other 2.0 scripts load project.py."""
    spec = importlib.util.spec_from_file_location('lf_track_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


project = load_sibling('project')
try:
    import numpy as np
except ImportError as missing:
    print(project.dependency_message(missing.name or 'numpy'), file=sys.stderr)
    sys.exit(2)

ANALYSIS_WIDTH = 1920  # wider sources are tracked at this width; coordinates are stored as fractions
DEFAULT_SPAN = 5.0  # seconds either side of --at when --from or --to is not given
FEATURES = 400  # features sought inside a region
MIN_AGREE = 10  # fewest RANSAC inliers that make a fit
MIN_INLIER_SHARE = 0.3
FB_LIMIT = 1.0  # pixels: a feature tracked back must land this close to where it started
RANSAC_PX = 2.0
MIN_LIKENESS = 0.45  # normalised correlation with the key frame's region below which the surface is lost
FOUND_LIKENESS = 0.6  # a surface found again after a loss must look this much like the key frame's
CUT_LEVEL = 18.0  # mean grey change (0-255, on a small copy) above which, well over the recent motion, a shot changes
MIN_VISIBLE = 0.2  # share of the region inside the frame below which it has left
LARGE_ERROR = 2.0  # displayed pixels: a frame error above this is reported for inspection


def cv():
    """OpenCV, imported only when tracking runs."""
    import cv2
    return cv2


# ----------------------------------------------------------------------------------------------- input

def parse_numbers(text, count_options, what):
    """Comma-separated numbers, as many as one of count_options."""
    try:
        values = [float(part) for part in str(text).split(',')]
    except ValueError:
        raise ValueError(f'{what} must be numbers separated by commas, not {text!r}') from None
    if len(values) not in count_options or not all(math.isfinite(value) for value in values):
        raise ValueError(f'{what} needs {" or ".join(map(str, count_options))} numbers, not {len(values)}')
    return values


def to_pixels(values, size):
    """Values as displayed pixels: fractions when every value is between 0 and 1."""
    if all(0 <= value <= 1 for value in values):
        return [value * size[index % 2] for index, value in enumerate(values)]
    return values


def parse_region(text, size):
    """--region as four corners in displayed pixels (continuous coordinates, pixel edges on integers)."""
    values = to_pixels(parse_numbers(text, (4, 8), '--region'), size)
    if len(values) == 4:
        x, y, w, h = values
        if w <= 0 or h <= 0:
            raise ValueError('--region width and height must be positive')
        corners = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    else:
        corners = [values[index:index + 2] for index in range(0, 8, 2)]
    corners = np.asarray(corners, dtype=np.float64)
    if polygon_area(corners) <= 16:
        raise ValueError('--region must enclose an area: give its corners clockwise from the top left')
    return corners


def parse_point(text, size):
    """--point in displayed pixels."""
    return np.asarray(to_pixels(parse_numbers(text, (2,), '--point'), size), dtype=np.float64)


def polygon_area(points):
    """Signed area (positive clockwise in image coordinates, y down)."""
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def resolve_source(source, root):
    """(path, alias) for a file or a map alias."""
    spatial = load_sibling('spatial')
    rows = spatial.map_rows(root)
    if root and source in rows:
        return spatial.map_path(root, rows[source]).resolve(), source
    path = Path(source).resolve()
    if not path.is_file():
        raise ValueError(f'no source file or alias {source}' + ('' if root else ' (an alias needs --project)'))
    return path, None


# ----------------------------------------------------------------------------------------------- decoding

class Spool:
    """Every frame of a source range as 8-bit grey at analysis size, decoded once by FFmpeg on assemble.py's clock
    (format start time subtracted, autorotated, square pixels) and kept in a temporary file, read back by index."""

    def __init__(self, path, start, stop, display, origin, analysis, folder):
        common = load_sibling('render_common')
        frames_module = load_sibling('motion_scan')
        ffmpeg = common.find_tool('ffmpeg')
        if not ffmpeg:
            raise ValueError('FFmpeg is required to decode the source')
        self.width, self.height = analysis
        self.bytes = self.width * self.height
        seek = max(0.0, start - 2.0) if common.source_seek_safe(str(path)) else 0.0
        clock = (f'trim=start={origin + max(0.0, start - 1.0):.9f}:end={origin + stop + 1e-6:.9f},'
                 f'setpts=PTS-({origin:.9f})/TB,')
        scale = f'scale={display[0]}:{display[1]}:flags=lanczos,setsar=1'
        if analysis != tuple(display):
            scale += f',scale={self.width}:{self.height}:flags=area'
        options = ['-copyts'] + (['-ss', f'{seek:.9f}'] if seek else []) + ['-t', f'{stop - seek + 2:.9f}']
        handle, name = tempfile.mkstemp(prefix='track-', suffix='.gray', dir=folder)
        os.close(handle)
        self.file = Path(name)
        reader = frames_module.Frames(ffmpeg, str(path), clock + scale + ',format=gray', self.bytes, options)
        count = 0
        changes = []
        previous = None
        with open(self.file, 'wb') as output:
            for raw in reader:
                output.write(raw)
                small = thumbnail(np.frombuffer(raw, dtype=np.uint8).reshape(self.height, self.width))
                changes.append(float(np.mean(np.abs(small - previous))) if previous is not None else 0.0)
                previous = small
                count += 1
        times = reader.times(count)
        first = max([index for index, value in enumerate(times) if value <= start + 1e-4] or [0])
        self.offset = first
        self.times = times[first:]
        self.cuts = shot_changes(changes[first:])
        self.handle = open(self.file, 'rb')

    def shot(self, key):
        """The first and last frame of the shot holding frame `key`."""
        before = [cut for cut in self.cuts if cut <= key]
        after = [cut for cut in self.cuts if cut > key]
        return (before[-1] if before else 0), (after[0] - 1 if after else len(self.times) - 1)

    def frame(self, index):
        """Frame `index` (within the kept range) as a (height, width) uint8 array."""
        self.handle.seek((index + self.offset) * self.bytes)
        raw = self.handle.read(self.bytes)
        if len(raw) != self.bytes:
            raise RuntimeError('short frame in the tracking spool')
        return np.frombuffer(raw, dtype=np.uint8).reshape(self.height, self.width)

    def close(self):
        """Remove the spool."""
        self.handle.close()
        self.file.unlink(missing_ok=True)


def thumbnail(gray):
    """A small float copy of a frame (block means), for finding shot changes."""
    step = max(1, gray.shape[1] // 120)
    height, width = gray.shape[0] // step * step, gray.shape[1] // step * step
    return gray[:height, :width].reshape(height // step, step, width // step, step).mean(axis=(1, 3))


def shot_changes(changes):
    """Frames that start a new shot: a picture change above CUT_LEVEL and well above the recent motion."""
    cuts = []
    for index in range(1, len(changes)):
        recent = changes[max(1, index - 12):index]
        usual = float(np.median(recent)) if recent else 0.0
        if changes[index] > CUT_LEVEL and changes[index] > 3 * usual + 6:
            cuts.append(index)
    return cuts


# ----------------------------------------------------------------------------------------------- measurement

def region_mask(shape, quad):
    """A filled mask of a quadrilateral (OpenCV pixel-centre coordinates)."""
    mask = np.zeros(shape, dtype=np.uint8)
    cv().fillConvexPoly(mask, np.round(quad * 16).astype(np.int32), 255, lineType=cv().LINE_8, shift=4)
    return mask


def shrink(quad, share):
    """A quadrilateral pulled towards its centre by `share` of its size."""
    centre = quad.mean(axis=0)
    return centre + (quad - centre) * (1 - share)


def detect(gray, quad, count, avoid=None):
    """Shi-Tomasi corners inside a quadrilateral, refined to sub-pixel, away from existing points."""
    cv2 = cv()
    mask = region_mask(gray.shape, shrink(quad, 0.03))
    if avoid is not None:
        for x, y in avoid:
            cv2.circle(mask, (int(round(x)), int(round(y))), 5, 0, -1)
    found = cv2.goodFeaturesToTrack(gray, maxCorners=count, qualityLevel=0.005, minDistance=6, mask=mask,
                                    blockSize=7)
    if found is None:
        return np.zeros((0, 2), dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 30, 0.01)
    refined = cv2.cornerSubPix(gray, found.astype(np.float32), (5, 5), (-1, -1), criteria)
    return refined.reshape(-1, 2)


def flow(prev, gray, points):
    """Lucas-Kanade flow of points from prev to gray, checked backward: (new points, forward-backward error, ok)."""
    cv2 = cv()
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 40, 0.01)
    options = {'winSize': (21, 21), 'maxLevel': 4, 'criteria': criteria}
    moved, forward, _ = cv2.calcOpticalFlowPyrLK(prev, gray, points.reshape(-1, 1, 2), None, **options)
    back, backward, _ = cv2.calcOpticalFlowPyrLK(gray, prev, moved, None, **options)
    error = np.linalg.norm(back.reshape(-1, 2) - points.reshape(-1, 2), axis=1)
    ok = (forward.ravel() == 1) & (backward.ravel() == 1) & (error < FB_LIMIT)
    return moved.reshape(-1, 2), error, ok


def visible_share(quad_matrix, key_quad, shape):
    """Share of the key region that lands inside the frame under a homography (sampled on a 12 x 12 grid)."""
    spatial = load_sibling('spatial')
    steps = (np.arange(12) + 0.5) / 12
    u, v = np.meshgrid(steps, steps)
    unit = np.stack([u.ravel(), v.ravel()], axis=1)
    square = spatial.homography([[0, 0], [1, 0], [1, 1], [0, 1]], key_quad)
    points = spatial.apply_homography(quad_matrix @ square, unit)
    inside = (points[:, 0] >= -0.5) & (points[:, 1] >= -0.5) & (points[:, 0] <= shape[1] - 0.5) & (
        points[:, 1] <= shape[0] - 0.5)
    return float(inside.mean())


def plausible(matrix, key_quad, shape):
    """Whether a fitted region is a convex quadrilateral of sensible size that is mostly in the frame."""
    spatial = load_sibling('spatial')
    quad = spatial.apply_homography(matrix, key_quad)
    if not np.all(np.isfinite(quad)):
        return False
    area = polygon_area(quad)
    key_area = polygon_area(key_quad)
    if area <= 0 or not 1 / 25 < area / key_area < 25:
        return False
    edges = [quad[(i + 1) % 4] - quad[i] for i in range(4)]
    signs = [edges[i][0] * edges[(i + 1) % 4][1] - edges[i][1] * edges[(i + 1) % 4][0] for i in range(4)]
    if not (all(s > 0 for s in signs) or all(s < 0 for s in signs)):
        return False
    return visible_share(matrix, key_quad, shape) >= MIN_VISIBLE


class Template:
    """The key frame's region, for the likeness test: the current frame is warped back onto it and compared by
    normalised correlation over the pixels that land inside the frame."""

    def __init__(self, gray, quad):
        quad = np.asarray(quad, dtype=np.float64)
        low = np.floor(quad.min(axis=0)).astype(int)
        high = np.ceil(quad.max(axis=0)).astype(int) + 1
        low = np.maximum(low, 0)
        high = np.minimum(high, [gray.shape[1], gray.shape[0]])
        self.offset = low
        self.size = (int(high[0] - low[0]), int(high[1] - low[1]))
        crop = gray[low[1]:high[1], low[0]:high[0]].astype(np.float32)
        self.mask = region_mask(crop.shape, shrink(quad - low, 0.04)) > 0
        self.values = crop

    def likeness(self, gray, matrix):
        """Normalised correlation of the region now (through matrix: key frame to now) with the key frame."""
        cv2 = cv()
        shift = np.array([[1, 0, self.offset[0]], [0, 1, self.offset[1]], [0, 0, 1]], dtype=np.float64)
        warp = (matrix @ shift).astype(np.float64)
        flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
        now = cv2.warpPerspective(gray.astype(np.float32), warp, self.size, flags=flags, borderValue=-1)
        inside = self.mask & (now >= 0)
        if inside.sum() < 64:
            return 0.0
        a = self.values[inside] - self.values[inside].mean()
        b = now[inside] - now[inside].mean()
        scale = math.sqrt(float(np.dot(a, a)) * float(np.dot(b, b)))
        return float(np.dot(a, b) / scale) if scale > 0 else 0.0


# ----------------------------------------------------------------------------------------------- trackers

class RegionTracker:
    """A planar region followed from a start frame. Features keep their start-frame positions, so every frame is fitted
    to the start frame directly (no frame-to-frame chaining); features found later inherit start-frame positions
    through the inverse of the current fit."""

    def __init__(self, gray, quad):
        cv2 = cv()
        self.key_quad = np.asarray(quad, dtype=np.float64)
        self.template = Template(gray, self.key_quad)
        self.ref = detect(gray, self.key_quad, FEATURES).astype(np.float64)
        self.cur = self.ref.copy()
        self.initial = len(self.ref)
        self.matrix = np.eye(3)
        self.lost = len(self.ref) < MIN_AGREE
        self.key_gray = gray
        self.key_features = self.ref.copy()
        self.sift = cv2.SIFT_create(nfeatures=1500)
        mask = region_mask(gray.shape, self.key_quad)
        self.key_points, self.key_descriptors = self.sift.detectAndCompute(gray, mask)

    def fit(self, ref, now):
        """A RANSAC homography from start-frame positions to positions now, refined on its inliers."""
        cv2 = cv()
        matrix, mask = cv2.findHomography(ref.astype(np.float32), now.astype(np.float32), cv2.RANSAC, RANSAC_PX,
                                          maxIters=3000, confidence=0.999)
        if matrix is None:
            return None, None
        inliers = mask.ravel() == 1
        if inliers.sum() >= MIN_AGREE:
            refined, _ = cv2.findHomography(ref[inliers].astype(np.float32), now[inliers].astype(np.float32), 0)
            if refined is not None:
                matrix = refined
        return matrix, inliers

    def accept(self, gray, matrix):
        """Whether a fit passes the shape and likeness tests; (ok, likeness)."""
        if matrix is None or not plausible(matrix, self.key_quad, gray.shape):
            return False, 0.0
        likeness = self.template.likeness(gray, matrix)
        return likeness >= MIN_LIKENESS, likeness

    def reseed(self, gray, matrix, keep_cur=None, keep_ref=None):
        """Add features found now inside the fitted region, with start-frame positions through the inverse fit."""
        spatial = load_sibling('spatial')
        quad = spatial.apply_homography(matrix, self.key_quad)
        found = detect(gray, quad, FEATURES, keep_cur)
        if len(found):
            back = spatial.apply_homography(np.linalg.inv(matrix), found)
            keep_cur = found if keep_cur is None else np.vstack([keep_cur, found])
            keep_ref = back if keep_ref is None else np.vstack([keep_ref, back])
        self.cur = keep_cur if keep_cur is not None else np.zeros((0, 2))
        self.ref = keep_ref if keep_ref is not None else np.zeros((0, 2))
        self.initial = max(self.initial, len(self.cur)) if len(self.cur) else self.initial

    def measured(self, matrix, ref, now, fb_error=None):
        """A fit's error in pixels: the largest of its RMS residual, the median forward-backward error and the corner
        spread, how far the region's corners move between fits to two halves of the agreeing features (it grows
        where the corners are extrapolated far from the features, as when most of the surface is out of frame)."""
        cv2 = cv()
        spatial = load_sibling('spatial')
        residual = np.linalg.norm(spatial.apply_homography(matrix, ref) - now, axis=1)
        error = float(np.sqrt(np.mean(residual ** 2)))
        if fb_error is not None and len(fb_error):
            error = max(error, float(np.median(fb_error)))
        if len(ref) >= 2 * MIN_AGREE:
            order = np.random.default_rng(len(ref)).permutation(len(ref))
            halves = (order[::2], order[1::2])
            fits = [cv2.findHomography(ref[half].astype(np.float32), now[half].astype(np.float32), 0)[0]
                    for half in halves]
            if all(fit is not None for fit in fits):
                corners = [spatial.apply_homography(fit, self.key_quad) for fit in fits]
                error = max(error, float(np.max(np.linalg.norm(corners[0] - corners[1], axis=1))) / 2)
        return error

    def align(self, gray, matrix):
        """Refine a fit against the key frame itself: warp this frame back into the key frame's geometry (where the
        surface looks as it did there), flow the key frame's features into the warped picture and fold the small
        correction into the fit, twice. Returns (matrix, error, inliers) or None when it cannot be measured."""
        cv2 = cv()
        spatial = load_sibling('spatial')
        if len(self.key_features) < MIN_AGREE:
            return None
        (ox, oy), size = self.template.offset, self.template.size
        shift = np.array([[1, 0, ox], [0, 1, oy], [0, 0, 1]], dtype=np.float64)
        key_crop = np.ascontiguousarray(self.key_gray[oy:oy + size[1], ox:ox + size[0]])
        points = (self.key_features - [ox, oy]).astype(np.float32)
        height, width = gray.shape
        result = None
        for _ in range(2):
            landing = spatial.apply_homography(matrix, self.key_features)
            inside = ((landing[:, 0] >= 8) & (landing[:, 1] >= 8) & (landing[:, 0] <= width - 9)
                      & (landing[:, 1] <= height - 9))
            warped = cv2.warpPerspective(gray, matrix @ shift, size, flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
            moved, fb_error, ok = flow(key_crop, warped, points)
            ok &= inside
            if ok.sum() < MIN_AGREE:
                return result
            correction, inliers = self.fit(points[ok].astype(np.float64), moved[ok].astype(np.float64))
            if correction is None or inliers.sum() < MIN_AGREE:
                return result
            now = spatial.apply_homography(matrix @ shift, moved[ok][inliers])
            matrix = matrix @ shift @ correction @ np.linalg.inv(shift)
            matrix = matrix / matrix[2, 2]
            error = self.measured(matrix, self.key_features[ok][inliers], now, fb_error[ok][inliers])
            result = (matrix, error, int(inliers.sum()))
        return result

    def recover(self, gray):
        """Find the region again by matching the start frame's SIFT features, then refine it from the key frame's
        features: (matrix, error, inliers) or None."""
        cv2 = cv()
        if self.key_descriptors is None or len(self.key_points) < MIN_AGREE:
            return None
        points, descriptors = self.sift.detectAndCompute(gray, None)
        if descriptors is None or len(points) < MIN_AGREE:
            return None
        pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(self.key_descriptors, descriptors, k=2)
        good = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance]
        if len(good) < MIN_AGREE:
            return None
        ref = np.float64([self.key_points[m.queryIdx].pt for m in good])
        now = np.float64([points[m.trainIdx].pt for m in good])
        matrix, inliers = self.fit(ref, now)
        if matrix is None or inliers.sum() < MIN_AGREE:
            return None
        refined = self.align(gray, matrix)
        if refined is not None:
            return refined
        return matrix, self.measured(matrix, ref[inliers], now[inliers]), int(inliers.sum())

    def recovered(self, gray):
        """A step result from re-detection, or a lost one. A surface found again must look more like the key frame
        than one followed from the previous frame, because a look-alike elsewhere in the frame is the usual mistake."""
        found = self.recover(gray)
        ok, likeness = self.accept(gray, found[0] if found else None)
        if not ok or likeness < FOUND_LIKENESS:
            self.lost = True
            return {'state': 'lost', 'likeness': round(likeness, 3)}
        matrix, error, inliers = found
        self.lost = False
        self.matrix = matrix
        self.reseed(gray, matrix)
        return {'state': 'tracked', 'matrix': matrix, 'error': error, 'inliers': inliers,
                'likeness': round(likeness, 3), 'recovered': True}

    def step(self, prev, gray):
        """Advance one frame: {'state': 'tracked' | 'lost', 'matrix', 'error', 'inliers', 'likeness'}. When the flow
        from the previous frame does not give a fit that passes, the region is looked for again in this frame."""
        if self.lost or len(self.cur) < MIN_AGREE:
            return self.recovered(gray)
        moved, fb_error, ok = flow(prev, gray, self.cur.astype(np.float32))
        if ok.sum() < MIN_AGREE:
            return self.recovered(gray)
        matrix, inliers = self.fit(self.ref[ok], moved[ok].astype(np.float64))
        if matrix is None or inliers.sum() < max(MIN_AGREE, MIN_INLIER_SHARE * ok.sum()):
            return self.recovered(gray)
        accepted, likeness = self.accept(gray, matrix)
        if not accepted:
            return self.recovered(gray)
        kept_ref = self.ref[ok][inliers]
        kept_cur = moved[ok][inliers].astype(np.float64)
        error = self.measured(matrix, kept_ref, kept_cur, fb_error[ok][inliers])
        aligned = self.align(gray, matrix)
        if aligned is not None and self.accept(gray, aligned[0])[0]:
            matrix, error = aligned[0], aligned[1]
        self.matrix = matrix
        if len(kept_cur) < max(60, 0.5 * self.initial):
            self.reseed(gray, matrix, kept_cur, kept_ref)
        else:
            self.cur, self.ref = kept_cur, kept_ref
        return {'state': 'tracked', 'matrix': matrix, 'error': error, 'inliers': int(inliers.sum()),
                'likeness': round(likeness, 3)}

    def position(self, result):
        """The region's corners for a step result (OpenCV pixel-centre coordinates)."""
        return load_sibling('spatial').apply_homography(result['matrix'], self.key_quad)


class PointTracker:
    """One point followed by the median movement of features around it (translation only)."""

    def __init__(self, gray, point):
        self.point = np.asarray(point, dtype=np.float64)
        self.radius = max(12.0, 0.03 * gray.shape[1])
        self.patch = self.window(gray, self.point)
        self.feature_set(gray)
        self.lost = len(self.cur) < 4

    def window(self, gray, centre):
        """The square around a point as a quadrilateral."""
        r = self.radius
        x, y = centre
        return np.array([[x - r, y - r], [x + r, y - r], [x + r, y + r], [x - r, y + r]])

    def feature_set(self, gray):
        """Features around the current point and their offsets from it."""
        self.cur = detect(gray, self.window(gray, self.point), 80).astype(np.float64)
        self.offsets = self.cur - self.point
        self.initial = len(self.cur)
        self.template = Template(gray, self.window(gray, self.point))

    def search(self, gray):
        """After a loss, look for the last good patch near where the point was: a step result, or a lost one."""
        cv2 = cv()
        patch = self.template
        size = patch.size
        reach = int(3 * self.radius)
        x0 = max(0, int(self.point[0] - self.radius) - reach)
        y0 = max(0, int(self.point[1] - self.radius) - reach)
        x1 = min(gray.shape[1], int(self.point[0] + self.radius) + reach + 1)
        y1 = min(gray.shape[0], int(self.point[1] + self.radius) + reach + 1)
        if x1 - x0 <= size[0] or y1 - y0 <= size[1]:
            return {'state': 'lost', 'likeness': None}
        scores = cv2.matchTemplate(gray[y0:y1, x0:x1].astype(np.float32), patch.values, cv2.TM_CCOEFF_NORMED)
        _, best, _, where = cv2.minMaxLoc(scores)
        if best < FOUND_LIKENESS + 0.1:
            return {'state': 'lost', 'likeness': round(float(best), 3)}
        offset = self.point - patch.offset
        centre = np.array([x0 + where[0], y0 + where[1]], dtype=np.float64) + offset
        self.point = centre
        self.feature_set(gray)
        self.lost = len(self.cur) < 4
        if self.lost:
            return {'state': 'lost', 'likeness': round(float(best), 3)}
        return {'state': 'tracked', 'point': centre, 'error': 1.0, 'inliers': len(self.cur),
                'likeness': round(float(best), 3), 'recovered': True}

    def step(self, prev, gray):
        """Advance one frame: {'state', 'point', 'error', 'inliers', 'likeness'}. The point's patch is compared with
        its last good look (a face turns, a plate tilts); after a loss it is looked for near its last place."""
        if self.lost or len(self.cur) < 4:
            return self.search(gray)
        moved, fb_error, ok = flow(prev, gray, self.cur.astype(np.float32))
        if ok.sum() < 4:
            self.lost = True
            return {'state': 'lost', 'likeness': None}
        estimates = moved[ok] - self.offsets[ok]
        centre = np.median(estimates, axis=0)
        spread = np.linalg.norm(estimates - centre, axis=1)
        agree = spread <= max(1.5, 3 * float(np.median(spread)))
        if agree.sum() < 4:
            self.lost = True
            return {'state': 'lost', 'likeness': None}
        centre = np.median(estimates[agree], axis=0)
        shift = centre - self.point
        matrix = np.array([[1, 0, shift[0]], [0, 1, shift[1]], [0, 0, 1]], dtype=np.float64)
        likeness = self.template.likeness(gray, matrix)  # against the last good patch
        if likeness < MIN_LIKENESS:
            self.lost = True
            return {'state': 'lost', 'likeness': round(likeness, 3)}
        error = max(float(np.median(spread[agree])), float(np.median(fb_error[ok][agree])))
        kept = moved[ok][agree].astype(np.float64)
        offsets = self.offsets[ok][agree]
        self.cur, self.offsets = kept, offsets
        if len(self.cur) < max(12, 0.5 * self.initial):
            fresh = detect(gray, self.window(gray, centre), 80, self.cur).astype(np.float64)
            self.cur = np.vstack([self.cur, fresh])
            self.offsets = np.vstack([self.offsets, fresh - centre])
        self.point = centre
        self.template = Template(gray, self.window(gray, centre))
        return {'state': 'tracked', 'point': centre, 'error': error, 'inliers': int(agree.sum()),
                'likeness': round(likeness, 3)}

    def position(self, result):
        """The point for a step result."""
        return result['point']


# ----------------------------------------------------------------------------------------------- runs

def run(spool, start, stop, make, shape):
    """Track from frame `start` towards `stop` (inclusive, either direction): {index: result}, the start excluded."""
    step = 1 if stop >= start else -1
    tracker = make(spool.frame(start))
    results = {}
    prev = spool.frame(start)
    for index in range(start + step, stop + step, step):
        gray = spool.frame(index)
        result = tracker.step(prev, gray)
        if result['state'] == 'tracked':
            result['position'] = tracker.position(result)
        results[index] = result
        prev = gray
    return results


def drift(spool, end, key, position, key_position, make):
    """Track from a range end back to the key frame, starting from the position tracked there: the mean distance
    of the arrival position from the key frame's (OpenCV pixels), or None when it is lost on the way back."""
    if end == key or position is None:
        return None
    results = run(spool, end, key, lambda gray: make(gray, position), None)
    arrival = results.get(key)
    if not arrival or arrival['state'] != 'tracked':
        return None
    return float(np.mean(np.linalg.norm(np.reshape(arrival['position'], (-1, 2))
                                        - np.reshape(key_position, (-1, 2)), axis=1)))


def last_tracked(results, indices):
    """The last index (in the given order) whose result was tracked, with its position."""
    for index in reversed(indices):
        result = results.get(index)
        if result and result['state'] == 'tracked':
            return index, result['position']
    return None, None


def track(spool, key, key_position, mode):
    """Track forward and backward from the key frame; returns (results by index, drift measurements)."""
    if mode == 'region':
        def make(gray, position):
            return RegionTracker(gray, position)
    else:
        def make(gray, position):
            return PointTracker(gray, position)
    first, last = spool.shot(key)
    forward = run(spool, key, last, lambda gray: make(gray, key_position), None)
    backward = run(spool, key, first, lambda gray: make(gray, key_position), None)
    results = {**forward, **backward}
    for index in range(len(spool.times)):
        if index != key and index not in results:
            results[index] = {'state': 'lost', 'reason': 'another shot'}
    drifts = {}
    for name, indices in (('forward', list(range(key + 1, last + 1))), ('backward', list(range(key - 1, first - 1,
                                                                                                 -1)))):
        if not indices:
            continue
        end, position = last_tracked(results, indices)
        if end is None:
            drifts[name] = {'state': 'not measured', 'reason': 'every frame on this side is lost'}
            continue
        measured = drift(spool, end, key, position, key_position, make)
        drifts[name] = ({'state': 'measured', 'from_index': end, 'px': measured} if measured is not None else
                        {'state': 'not measured', 'from_index': end,
                         'reason': 'tracking back to the key frame lost the region'})
    return results, drifts


# ----------------------------------------------------------------------------------------------- the layer

def frames_out(spool, key, key_position, results, mode, display, scale):
    """The layer's frames: positions as fractions of the displayed frame, error in displayed pixels."""
    rows = []
    size = np.array(display, dtype=np.float64)
    for index in range(len(spool.times)):
        if index == key:
            result = {'state': 'key', 'position': key_position, 'error': 0.0}
        else:
            result = results[index]
        if result['state'] == 'lost':
            rows.append({'state': 'lost'})
            continue
        # OpenCV coordinates put pixel centres on integers; the layer puts pixel edges on integers.
        position = (np.reshape(result['position'], (-1, 2)) + 0.5) * scale / size
        row = {'state': result['state']}
        if mode == 'region':
            row['corners'] = [[round(float(x), 6), round(float(y), 6)] for x, y in position]
        else:
            row['point'] = [round(float(position[0][0]), 6), round(float(position[0][1]), 6)]
        row['error_px'] = round(float(result['error']) * scale, 3)
        rows.append(row)
    return rows


def quality(rows, drifts, scale, times):
    """The layer's measured summary."""
    errors = [row['error_px'] for row in rows if row['state'] == 'tracked']
    lost = [index for index, row in enumerate(rows) if row['state'] == 'lost']
    summary = {'frames': len(rows), 'tracked': len(rows) - len(lost), 'lost': len(lost),
               'error_px_median': round(float(np.median(errors)), 3) if errors else None,
               'error_px_worst': round(float(max(errors)), 3) if errors else None}
    measured = [row['px'] * scale for row in drifts.values() if row['state'] == 'measured']
    summary['drift_px'] = round(max(measured), 3) if measured else None
    summary['drift'] = {name: ({'from_s': round(times[row['from_index']], 6), 'px': round(row['px'] * scale, 3)}
                               if row['state'] == 'measured' else
                               {'not_measured': row['reason']}) for name, row in drifts.items()}
    if lost:
        spans, start = [], lost[0]
        for previous, index in zip(lost, lost[1:] + [None]):
            if index != previous + 1:
                spans.append([round(times[start], 6), round(times[previous], 6)])
                start = index
        summary['lost_spans_s'] = spans[:50]
    summary['units'] = 'displayed pixels; drift is a round trip from each range end back to the key frame'
    return summary


def output_path(args, root):
    """Where the sidecar goes."""
    spatial = load_sibling('spatial')
    if args.out:
        if not spatial.NAME.match(args.name):
            raise ValueError(f'a layer name is lowercase letters, digits and hyphens, not {args.name!r}')
        return Path(args.out).resolve() / f'{args.name}.json'
    if not root:
        raise ValueError('give --project PROJECT or --out DIR')
    return spatial.sidecar_path(root, args.name)


def main(argv=None):
    """Track a region or point and write the layer."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source')
    parser.add_argument('--at', required=True, help='the key frame time (source time)')
    shape = parser.add_mutually_exclusive_group(required=True)
    shape.add_argument('--region')
    shape.add_argument('--point')
    parser.add_argument('--from', dest='start')
    parser.add_argument('--to', dest='stop')
    parser.add_argument('--name', required=True)
    place = parser.add_mutually_exclusive_group()
    place.add_argument('--project')
    place.add_argument('--out')
    args = parser.parse_args(argv)
    project.safe_output()
    try:
        cv()
    except ImportError:
        print('track: cannot run: ' + project.dependency_message('cv2'), file=sys.stderr)
        return 2
    spool = None
    try:
        spatial = load_sibling('spatial')
        root = Path(args.project).resolve() if args.project else None
        path, _ = resolve_source(args.source, root)
        target = output_path(args, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        block, display = spatial.bind_source(path, target.parent, root)
        at = project.parse_time(args.at)
        start = project.parse_time(args.start) if args.start else max(0.0, at - DEFAULT_SPAN)
        stop = project.parse_time(args.stop) if args.stop else at + DEFAULT_SPAN
        if not start <= at <= stop:
            raise ValueError('--at must lie between --from and --to')
        mode = 'region' if args.region else 'point'
        shown = parse_region(args.region, display) if args.region else parse_point(args.point, display)
        scale = max(1.0, display[0] / ANALYSIS_WIDTH)
        analysis = (max(2, round(display[0] / scale / 2) * 2), max(2, round(display[1] / scale / 2) * 2))
        scale = display[0] / analysis[0]
        spool = Spool(path, start, stop, display, block['origin_s'], analysis, str(target.parent))
        key = spatial.frame_index(spool.times, at)
        if key is None:
            raise ValueError(f'no frame at {args.at} in the decoded range')
        key_position = np.reshape(shown, (-1, 2)) / scale - 0.5
        if mode == 'point':
            key_position = key_position[0]
        results, drifts = track(spool, key, key_position, mode)
        rows = frames_out(spool, key, key_position, results, mode, display, scale)
        summary = quality(rows, drifts, scale, spool.times)
        shot = spool.shot(key)
        summary['shot_s'] = [round(spool.times[shot[0]], 6), round(spool.times[shot[1]], 6)]
        summary['shot_changes_s'] = [round(spool.times[cut], 6) for cut in spool.cuts]
        cv2 = cv()
        layer = {'version': spatial.VERSION, 'kind': 'track', 'source': block, 'frame_size': list(display),
                 'clock': 'source', 'times': [round(value, 9) for value in spool.times], 'frames': rows,
                 'method': {'tool': 'track.py', 'backend': 'opencv',
                            'algorithm': ('Shi-Tomasi features, pyramidal Lucas-Kanade with a forward-backward '
                                          'check, RANSAC homography from the key frame, SIFT re-detection after a '
                                          'loss' if mode == 'region' else
                                          'Shi-Tomasi features, pyramidal Lucas-Kanade with a forward-backward '
                                          'check, median translation'),
                            'opencv': cv2.__version__, 'mode': mode, 'licence': 'not applicable (no model)',
                            'params': {'key_s': round(spool.times[key], 6), 'from_s': start, 'to_s': stop,
                                       'analysis_size': list(analysis), 'fb_limit_px': FB_LIMIT,
                                       'ransac_px': RANSAC_PX, 'min_likeness': MIN_LIKENESS}},
                 'quality': summary}
        layer = spatial.write_layer(target, layer)
        print(f"wrote {target}: {summary['tracked']} of {summary['frames']} frames tracked, {summary['lost']} lost; "
              f"error median {summary['error_px_median']} px, worst {summary['error_px_worst']} px; drift "
              f"{summary['drift_px'] if summary['drift_px'] is not None else 'not measured'} px")
        for cut in summary['shot_changes_s']:
            print(f'shot change at {cut:.3f} s: frames in another shot are lost (a track never crosses a cut)')
        for span in summary.get('lost_spans_s', [])[:10]:
            print(f'lost: {span[0]:.3f}-{span[1]:.3f} s source time')
        large = (summary['error_px_worst'] or 0) > LARGE_ERROR
        if large:
            print(f'look: the worst frame error is {summary["error_px_worst"]} px; inspect those frames')
        return 1 if summary['lost'] or large else 0
    except (OSError, ValueError, RuntimeError, IndexError) as error:
        print(f'track: cannot run: {error}', file=sys.stderr)
        return 2
    finally:
        if spool is not None:
            spool.close()


if __name__ == '__main__':
    sys.exit(main())

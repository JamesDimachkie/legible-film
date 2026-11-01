"""Known-answer cases for spatial layers: spatial.py (the layer contract), track.py (planar and point tracking) and
assemble.py's pin, behind and blur overlays, on synthetic media made here with numpy and FFmpeg.

Tracking cases need OpenCV; without it they print 'skipped: <reason>' and record nothing. Every other case runs on
the core dependencies, building its track layers from known geometry."""
import contextlib
import importlib.util
import io
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def load(scripts_dir, name):
    """A sibling script as a module."""
    spec = importlib.util.spec_from_file_location(f'spatial_case_{name}', Path(scripts_dir) / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def have_cv2():
    """Whether OpenCV imports here."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


def encode(path, frames, size, rate=25, pix_fmt='gray', before=(), after=()):
    """Encode numpy frames (gray or rgb24) to H.264 through FFmpeg."""
    command = ['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', pix_fmt, '-s',
               f'{size[0]}x{size[1]}', '-framerate', str(rate), '-i', 'pipe:0', *before, '-c:v', 'libx264',
               '-crf', '10', '-pix_fmt', 'yuv420p', *after, str(path)]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE)
    for frame in frames:
        proc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError('could not encode a synthetic source')


def decode(path, size):
    """Every displayed frame of a small video as (h, w, 3) uint8 arrays."""
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                         capture_output=True, check=True).stdout
    count = len(raw) // (size[0] * size[1] * 3)
    return list(np.frombuffer(raw[:count * size[0] * size[1] * 3], np.uint8).reshape(count, size[1], size[0], 3))


def texture(width, height, seed):
    """Smooth random detail (three octaves of interpolated noise), 18-238."""
    rng = np.random.default_rng(seed)
    out = np.zeros((height, width))
    for cell, weight in ((24, 1.0), (8, 0.6), (3, 0.3)):
        small = rng.random((height // cell + 2, width // cell + 2))
        ys, xs = (np.arange(height) + 0.5) / cell, (np.arange(width) + 0.5) / cell
        y0, x0 = np.floor(ys).astype(int), np.floor(xs).astype(int)
        fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
        out += weight * ((small[y0][:, x0] * (1 - fx) + small[y0][:, x0 + 1] * fx) * (1 - fy)
                         + (small[y0 + 1][:, x0] * (1 - fx) + small[y0 + 1][:, x0 + 1] * fx) * fy)
    out -= out.min()
    return out / out.max() * 220 + 18


def warp_plane(tex, background, matrix):
    """The textured plane drawn over a background through a homography (plane pixels to frame pixels), sampled
    bilinearly at pixel centres."""
    height, width = background.shape
    th, tw = tex.shape
    ys, xs = np.mgrid[0:height, 0:width]
    mapped = np.linalg.inv(matrix) @ np.stack([xs.ravel() + .5, ys.ravel() + .5, np.ones(xs.size)])
    u, v = mapped[0] / mapped[2] - .5, mapped[1] / mapped[2] - .5
    inside = (u >= -.5) & (v >= -.5) & (u <= tw - .5) & (v <= th - .5)
    u, v = np.clip(u, 0, tw - 1.001), np.clip(v, 0, th - 1.001)
    x0, y0 = np.floor(u).astype(int), np.floor(v).astype(int)
    fx, fy = u - x0, v - y0
    value = ((tex[y0, x0] * (1 - fx) + tex[y0, x0 + 1] * fx) * (1 - fy)
             + (tex[y0 + 1, x0] * (1 - fx) + tex[y0 + 1, x0 + 1] * fx) * fy)
    out = background.ravel().copy()
    out[inside] = value[inside]
    return out.reshape(height, width)


def write_track(spatial, source, sidecar, corners_by_frame, states=None, points=None, root=None):
    """A track layer for `source` from known corners (fractions) per decoded frame, on the source's decoded clock;
    bound through the project's map when `root` is given."""
    Path(sidecar).parent.mkdir(parents=True, exist_ok=True)
    block, size = spatial.bind_source(source, Path(sidecar).parent, root)
    times = spatial.source_frame_times(source, 0.0, 1e6, block['origin_s'])
    frames = []
    for index in range(len(times)):
        state = (states or {}).get(index, 'key' if index == 0 else 'tracked')
        if state == 'lost':
            frames.append({'state': 'lost'})
        elif points is not None:
            frames.append({'state': state, 'point': [float(v) for v in points[index]], 'error_px': 0.0})
        else:
            frames.append({'state': state, 'corners': [[float(x), float(y)] for x, y in corners_by_frame[index]],
                           'error_px': 0.0})
    layer = {'version': 1, 'kind': 'track', 'source': block, 'frame_size': size, 'clock': 'source',
             'times': times, 'frames': frames, 'method': {'tool': 'selftest', 'backend': 'known geometry'},
             'quality': {}}
    return spatial.write_layer(sidecar, layer)


def write_matte(spatial, source, sidecar, masks):
    """A matte layer for `source` from known masks (uint8 arrays, one per decoded frame)."""
    block, size = spatial.bind_source(source, Path(sidecar).parent)
    times = spatial.source_frame_times(source, 0.0, 1e6, block['origin_s'])
    data = Path(sidecar).with_suffix('.matte.mkv')
    spatial.write_frames(data, masks[:len(times)], size)
    layer = {'version': 1, 'kind': 'matte', 'source': block, 'frame_size': size, 'clock': 'source',
             'times': times, 'data': data.name, 'method': {'tool': 'selftest', 'backend': 'known masks'},
             'quality': {}}
    return spatial.write_layer(sidecar, spatial.seal_data(sidecar, layer))


def render(tool, folder, edit, name='out'):
    """Run assemble.py on an edit: (exit code, output, report or {})."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{name}.json').write_text(json.dumps(edit), encoding='utf-8')
    code, output = tool('assemble.py', folder / f'{name}.json', '--out', folder / name / 'picture.mp4')
    report = folder / name / 'assemble-report.json'
    return code, output, json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}


def red_mask(frame):
    """Pixels the red overlay covers."""
    rgb = frame.astype(int)
    return (rgb[..., 0] - rgb[..., 1] > 90) & (rgb[..., 0] - rgb[..., 2] > 90)


def polygon_centroid(points):
    """Area centroid of a polygon."""
    x, y = points[:, 0], points[:, 1]
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    area = cross.sum() / 2
    return np.array([((x + np.roll(x, -1)) * cross).sum(), ((y + np.roll(y, -1)) * cross).sum()]) / (6 * area)


def inside_polygon(points, shape):
    """A boolean mask of pixel centres inside a convex polygon."""
    ys, xs = np.mgrid[0:shape[0], 0:shape[1]]
    px, py = xs + .5, ys + .5
    signs = []
    for index in range(len(points)):
        (ax, ay), (bx, by) = points[index], points[(index + 1) % len(points)]
        signs.append((bx - ax) * (py - ay) - (by - ay) * (px - ax))
    signs = np.stack(signs)
    return np.all(signs >= 0, axis=0) | np.all(signs <= 0, axis=0)


def moving_quad(index, size):
    """A known quadrilateral (fractions) that turns and slides with the frame number."""
    angle = 0.02 * index
    centre = np.array([0.45 + 0.004 * index, 0.5 + 0.002 * index])
    base = np.array([[-.18, -.14], [.2, -.12], [.17, .15], [-.16, .13]])
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    aspect = np.array([1.0, size[0] / size[1]])
    return centre + (base * aspect) @ rotation.T / aspect


def card(path, colour=(255, 0, 0, 255), size=(160, 100)):
    """A solid overlay image."""
    Image.new('RGBA', size, colour).save(path)


# ----------------------------------------------------------------------------------------------- contract

def check_contract(record, spatial, j):
    """Mattes keep every value exactly (0 and 255 included) and are read by frame order; lookups pick the last
    frame at or before a time within half a frame; invalid sidecars are refused with the reason."""
    folder = Path(j('spatial-contract'))
    folder.mkdir(parents=True, exist_ok=True)
    values = [0, 1, 127, 128, 254, 255]
    frames = [np.full((36, 64), values[index % 6], np.uint8) for index in range(8)]
    for index, frame in enumerate(frames):
        frame[5:20, index * 4:index * 4 + 20] = 255 - frame[0, 0]
    count = spatial.write_frames(folder / 'm.mkv', frames, (64, 36))
    reader = spatial.FrameReader(folder / 'm.mkv', (64, 36))
    order = [0, 3, 7, 2, 5]
    exact = all(np.array_equal(reader.frame(index), frames[index]) for index in order)
    reader.close()
    record('spatial: matte frames round-trip exactly through FFV1 (0 and 255 survive) and are read by order, '
           'backwards too', count == 8 and exact, str((count, exact)))
    vfr = [0.0, 0.04, 0.087, 0.12, 0.2]
    picks = [spatial.frame_index(vfr, moment) for moment in (-0.01, 0.0, 0.039, 0.086, 0.119, 0.19, 0.239, 0.241)]
    matched = [spatial.match_frame(vfr, moment) for moment in (0.0401, 0.06, 0.0869, 0.2)]
    record('spatial: lookup takes the last frame at or before a time, within half a local frame; a renderer\'s '
           'selected frame matches only its own time',
           picks == [None, 0, 0, 1, 2, 3, 4, None] and matched == [1, None, 2, 4], str((picks, matched)))
    good = {'version': 1, 'kind': 'track', 'source': {'file': 'a.mp4', 'size': 10, 'sha256': 'a' * 64,
                                                       'video_stream': 0},
            'frame_size': [64, 36], 'clock': 'source', 'times': [0.0, 0.04],
            'frames': [{'state': 'key', 'corners': [[0, 0], [1, 0], [1, 1], [0, 1]]}, {'state': 'lost'}],
            'method': {'tool': 'x'}}
    broken = [dict(good, source=dict(good['source'], stream=0)),
              dict(good, frames=[dict(good['frames'][0], t=0.0), good['frames'][1]]),
              dict(good, times=[0.04, 0.0]), dict(good, frames=good['frames'][:1]),
              dict(good, frames=[good['frames'][0], {'state': 'lost', 'corners': good['frames'][0]['corners']}]),
              dict(good, kind='depth')]
    problems = [spatial.validate(layer) for layer in broken]
    record('spatial: the contract refuses an ambiguous stream field, a per-frame time beside times, times out of '
           'order, a frame count mismatch, corners on a lost frame and a depth layer',
           not spatial.validate(good) and all(problems), str(problems))


# ----------------------------------------------------------------------------------------------- the assembler

def check_pin(record, tool, spatial, j):
    """A corner-pinned overlay lands where the track's quadrilateral is on each frame, and leaves the rest alone."""
    folder = Path(j('spatial-pin'))
    folder.mkdir(parents=True, exist_ok=True)
    size = (320, 240)
    encode(folder / 'flat.mp4', [np.full((240, 320), 128, np.uint8)] * 25, size)
    quads = [moving_quad(index, size) for index in range(25)]
    write_track(spatial, folder / 'flat.mp4', folder / 'card.json', quads)
    card(folder / 'red.png')
    edit = {'version': 1, 'size': list(size), 'fps': 25,
            'sources': {'a': {'file': 'flat.mp4'}, 'red': {'file': 'red.png'}},
            'picture': [{'src': 'a', 'in': 0.0, 'out': 1.0}], 'audio': [],
            'overlays': [{'kind': 'image', 'src': 'red', 'from': 0.0, 'to': 1.0, 'x': 0, 'y': 0, 'w': 0.2,
                          'pin': {'layer': 'card.json', 'fit': 'corners', 'aspect': 'stretch'}}]}
    code, output, report = render(tool, folder, edit)
    frames = decode(folder / 'out' / 'picture.mp4', size) if code in (0, 1) else []
    worst_centre, worst_area, leaks = 0.0, 0.0, 0
    for index in (0, 8, 16, 24):
        if index >= len(frames):
            break
        quad = quads[index] * size
        mask = red_mask(frames[index])
        ys, xs = np.nonzero(mask)
        centre = np.array([xs.mean() + .5, ys.mean() + .5])
        worst_centre = max(worst_centre, float(np.linalg.norm(centre - polygon_centroid(quad))))
        area = abs(np.sum(quad[:, 0] * np.roll(quad[:, 1], -1) - np.roll(quad[:, 0], -1) * quad[:, 1])) / 2
        worst_area = max(worst_area, abs(mask.sum() - area) / area)
        middle = polygon_centroid(quad)
        outside = ~inside_polygon(middle + (quad - middle) * 1.15, mask.shape)
        leaks += int(np.sum(np.abs(frames[index][outside].astype(int) - 128) > 12))
    record('spatial: a corner-pinned overlay lands on the track\'s quadrilateral (centre within 1 px, area within '
           '4%) and nothing changes outside it',
           code == 0 and len(frames) == 25 and worst_centre < 1.0 and worst_area < 0.04 and leaks == 0,
           f'code {code} centre {worst_centre:.2f} area {worst_area:.3f} leaks {leaks} ' + output[-300:])
    return report


def check_swapped_matte(record, tool, spatial, j):
    """A matte whose frames were replaced after it was sealed (here by a valid, empty one) is stale for every use: a
    privacy blur over it stops the render instead of blurring nothing and reporting every frame drawn."""
    folder = Path(j('spatial-swapped'))
    folder.mkdir(parents=True, exist_ok=True)
    size = (160, 120)
    ys, xs = np.mgrid[0:120, 0:160]
    encode(folder / 'scene.mp4', [np.stack([xs + n, ys, 255 - xs], axis=2) for n in range(10)], size,
           pix_fmt='rgb24')
    full = np.zeros((120, 160), np.uint8)
    full[20:100, 40:120] = 255
    write_matte(spatial, folder / 'scene.mp4', folder / 'face.json', [full] * 10)
    spatial.write_frames(folder / 'face.matte.mkv', [np.zeros((120, 160), np.uint8)] * 10, size)
    layer = spatial.read_layer(folder / 'face.json')
    state = spatial.layer_state(folder / 'face.json', layer, folder)
    edit = {'version': 1, 'size': list(size), 'fps': 25, 'sources': {'a': {'file': 'scene.mp4'}},
            'picture': [{'src': 'a', 'in': 0.0, 'out': 0.4}], 'audio': [],
            'overlays': [{'kind': 'blur', 'region': {'layer': 'face.json'}, 'from': 0.0, 'to': 0.4}]}
    code, output, _ = render(tool, folder, edit)
    record('spatial: a matte replaced after it was sealed is stale without --verify, and a blur over it stops the '
           'render', state['state'] == 'stale' and any('matte data' in reason for reason in state['reasons'])
           and code == 2 and not (folder / 'out' / 'picture.mp4').exists(), f'{state} {code} ' + output[-300:])


def check_behind(record, tool, spatial, j, scripts_dir):
    """`behind` draws the title, then the matte's foreground over it: foreground pixels stay as they were."""
    assemble = load(scripts_dir, 'assemble')
    base = Image.fromarray(np.random.default_rng(3).integers(0, 256, (6, 8, 3), dtype=np.uint8))
    over = Image.new('RGB', (8, 6), (255, 0, 0))
    matte = np.zeros((6, 8), np.uint8)
    matte[:, :4] = 255
    matte[0, 4] = 128
    mixed = np.asarray(assemble.matte_over(over, base, matte))
    expected = (np.array([255, 0, 0]) * 127 + np.asarray(base)[0, 4].astype(int) * 128 + 127) // 255
    record('spatial: matte 255 keeps the picture exactly, 0 keeps the overlay, 128 mixes them',
           np.array_equal(mixed[:, :4], np.asarray(base)[:, :4]) and np.all(mixed[1:, 5:] == [255, 0, 0])
           and np.array_equal(mixed[0, 4], expected), str((mixed[0, 4], expected)))
    folder = Path(j('spatial-behind'))
    folder.mkdir(parents=True, exist_ok=True)
    size = (320, 240)
    ys, xs = np.mgrid[0:240, 0:320]
    rgb = [np.stack([40 + xs * 0.5 + index, 50 + ys * 0.6, 160 - xs * 0.2], axis=2) for index in range(20)]
    encode(folder / 'scene.mp4', rgb, size, pix_fmt='rgb24')
    masks = []
    for index in range(20):
        mask = np.zeros((240, 320), np.uint8)
        mask[30:210, 100 + 3 * index:200 + 3 * index] = 255
        masks.append(mask)
    write_matte(spatial, folder / 'scene.mp4', folder / 'person.json', masks)
    Image.new('RGBA', (320, 240), (255, 0, 0, 255)).save(folder / 'title.png')
    edit = {'version': 1, 'size': list(size), 'fps': 25,
            'sources': {'a': {'file': 'scene.mp4'}, 'title': {'file': 'title.png'}},
            'picture': [{'src': 'a', 'in': 0.0, 'out': 0.8}], 'audio': [],
            'overlays': [{'kind': 'image', 'src': 'title', 'from': 0.0, 'to': 0.8, 'x': 0, 'y': 0, 'w': 1.0,
                          'behind': {'layer': 'person.json'}}]}
    code, output, report = render(tool, folder, edit)
    plain = dict(edit, overlays=[])
    plain_code, _, _ = render(tool, folder, plain, 'plain')
    ok = code in (0, 1) and plain_code in (0, 1)
    worst_inside, red_outside, red_inside = 0.0, 1.0, 1.0
    if ok:
        drawn, clean = decode(folder / 'out' / 'picture.mp4', size), decode(folder / 'plain' / 'picture.mp4', size)
        for index in (0, 10, 19):
            inner = np.zeros((240, 320), bool)
            inner[36:204, 106 + 3 * index:194 + 3 * index] = True
            difference = np.abs(drawn[index].astype(int) - clean[index].astype(int))[inner]
            worst_inside = max(worst_inside, float(difference.mean()))
            added = red_mask(drawn[index]) & ~red_mask(clean[index])
            red_inside = min(red_inside, 1.0 - float(added[inner].mean()))
            outer = np.ones((240, 320), bool)
            outer[20:220, 90 + 3 * index:210 + 3 * index] = False
            red_outside = min(red_outside, float(red_mask(drawn[index])[outer].mean()))
    flicker = ((report.get('layers') or [{}])[0]).get('matte_flicker') or {}
    exact = composite_exact(assemble, folder, edit, masks)
    record('spatial: behind leaves every matte-foreground pixel of the composite exactly as the picture was, '
           'through the assembler\'s own frame choice and framing (before encoding)', exact is True, str(exact))
    record('spatial: behind keeps the matte\'s foreground in the encoded film (no title inside, mean difference '
           'under 2 levels of encoder noise) and the title everywhere else; the matte\'s change is reported',
           ok and worst_inside < 2.0 and red_inside == 1.0 and red_outside > 0.98 and 'mean' in flicker,
           f'{code} {plain_code} inside {worst_inside:.2f} clean {red_inside:.3f} red {red_outside:.3f} {flicker} '
           + output[-300:])


def composite_exact(assemble, folder, edit, masks):
    """Run the assembler's own conform, plan, frame choice and layer drawing in process for three frames and compare
    the foreground pixels with the picture before the overlay: True, or what differed."""
    import tempfile
    edit = json.loads(json.dumps(edit))
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        notes = []
        cache, _, _ = assemble.conform('ffmpeg', 'ffprobe', edit, folder, temp, 1 << 30, notes)
        clips = assemble.plan_picture(edit, folder, cache, 'ffmpeg', 'ffprobe', temp, notes)[0]
        images, _ = assemble.prepare_overlays(edit, folder, 320, [], notes)
        total = clips[-1]['at'] + clips[-1]['duration']
        for clip in clips:
            clip['_matching_grid'] = assemble.source_grid_matches(clip, 25)
        plan = assemble.LayerPlan(edit, folder, clips, images, 320, 240, 25,
                                  assemble.output_frame_count(total, 25, clips))
        handles = {clip['raw']: clip['raw'].open() if isinstance(clip['raw'], assemble.FrameSource)
                   else open(clip['raw'], 'rb') for clip in clips}
        try:
            for number in (0, 10, 19):
                time = number / 25
                base = assemble.render_clip(clips[0], time, handles, 320, 240)
                drawn = plan.draw(0, base, images[0][0], 1.0, time, number)
                foreground = masks[number] == 255
                if not np.array_equal(np.asarray(drawn)[foreground], np.asarray(base)[foreground]):
                    return f'frame {number}: foreground changed'
                if not np.all(np.asarray(drawn)[~foreground] == [255, 0, 0]):
                    return f'frame {number}: title missing outside the foreground'
        finally:
            plan.close()
            for handle in handles.values():
                handle.close()
    return True


def check_blur(record, tool, spatial, j):
    """A blur covers its padded region on every frame, and stops the render when a frame in it is lost."""
    folder = Path(j('spatial-blur'))
    folder.mkdir(parents=True, exist_ok=True)
    size = (320, 240)
    ys, xs = np.mgrid[0:240, 0:320]
    checker = np.where(((xs // 4) + (ys // 4)) % 2, 230, 25).astype(np.uint8)
    encode(folder / 'plate.mp4', [checker] * 25, size)
    quads = [np.array([[.3, .35], [.5, .35], [.5, .55], [.3, .55]]) + [0.006 * index, 0] for index in range(25)]
    write_track(spatial, folder / 'plate.mp4', folder / 'plate.json', quads)
    edit = {'version': 1, 'size': list(size), 'fps': 25, 'sources': {'a': {'file': 'plate.mp4'}},
            'picture': [{'src': 'a', 'in': 0.0, 'out': 1.0}], 'audio': [],
            'overlays': [{'kind': 'blur', 'region': {'layer': 'plate.json'}, 'from': 0.0, 'to': 1.0}]}
    code, output, report = render(tool, folder, edit)
    frames = decode(folder / 'out' / 'picture.mp4', size) if code in (0, 1) else []
    inside_spread, outside_spread = 255.0, 0.0
    for index in (0, 12, 24):
        if index >= len(frames):
            break
        quad = quads[index] * size
        grey = frames[index][..., 1].astype(float)
        inside_spread = min(inside_spread, 255 - float(grey[inside_polygon(quad, grey.shape)].std()))
        outside_spread = max(outside_spread, float(grey[:, :40].std()))
    row = (report.get('layers') or [{}])[0]
    record('spatial: a tracked blur flattens the region on every frame (spread under 25 levels) and leaves the '
           'rest sharp; the notes say a person checks every frame',
           code in (0, 1) and len(frames) == 25 and 255 - inside_spread < 25 and outside_spread > 80
           and row.get('drawn_frames') == 25 and 'checks every frame' in output,
           f'{code} inside {255 - inside_spread:.1f} outside {outside_spread:.1f} {row} ' + output[-300:])
    masks = []
    for index in range(25):
        mask = np.zeros((240, 320), np.uint8)
        mask[90:150, 120 + 2 * index:180 + 2 * index] = 255
        masks.append(mask)
    write_matte(spatial, folder / 'plate.mp4', folder / 'face.json', masks)
    matte_edit = dict(edit, overlays=[{'kind': 'blur', 'region': {'layer': 'face.json'}, 'from': 0.0, 'to': 1.0}])
    code, output, _ = render(tool, folder, matte_edit, 'matte')
    frames = decode(folder / 'matte' / 'picture.mp4', size) if code in (0, 1) else []
    spreads = [float(frames[index][90:150, 120 + 2 * index:180 + 2 * index, 1].std()) for index in (0, 12, 24)
               if index < len(frames)]
    record('spatial: a blur over a matte layer flattens the matte\'s foreground on every frame',
           code in (0, 1) and len(frames) == 25 and max(spreads) < 25 and float(frames[0][:, :40, 1].std()) > 80,
           f'{code} {spreads} ' + output[-300:])
    layer = json.loads((folder / 'plate.json').read_text(encoding='utf-8'))
    for index in (10, 11, 12):
        layer['frames'][index] = {'state': 'lost'}
    (folder / 'plate.json').write_text(json.dumps(layer), encoding='utf-8')
    code, output, _ = render(tool, folder, edit, 'lost')
    record('spatial: a blur with lost frames inside its interval stops the render (exit 2) and names the times',
           code == 2 and 'lost' in output and '0:00.40-0:00.52' in output and not (folder / 'lost' /
                                                                                  'picture.mp4').exists(),
           f'{code} ' + output[-400:])


def check_wrong_source(record, tool, spatial, j):
    """A pin draws only over its own source: not under a cutaway from another source, not during a dissolve; the
    notes say where and why."""
    folder = Path(j('spatial-source'))
    folder.mkdir(parents=True, exist_ok=True)
    size = (320, 240)
    encode(folder / 'a.mp4', [np.full((240, 320), 128, np.uint8)] * 50, size)
    encode(folder / 'b.mp4', [np.full((240, 320), 60, np.uint8)] * 50, size)
    write_track(spatial, folder / 'a.mp4', folder / 'screen.json', [moving_quad(0, size)] * 50)
    card(folder / 'red.png')
    edit = {'version': 1, 'size': list(size), 'fps': 25,
            'sources': {'a': {'file': 'a.mp4'}, 'b': {'file': 'b.mp4'}, 'red': {'file': 'red.png'}},
            'picture': [{'src': 'a', 'in': 0.0, 'out': 0.4}, {'src': 'b', 'in': 0.0, 'out': 0.4},
                        {'src': 'a', 'in': 0.8, 'out': 1.6, 'join': {'kind': 'dissolve', 'dur': 0.2}}],
            'audio': [],
            'overlays': [{'kind': 'image', 'src': 'red', 'from': 0.0, 'to': 1.4, 'x': 0, 'y': 0, 'w': 0.2,
                          'pin': {'layer': 'screen.json'}}]}
    code, output, report = render(tool, folder, edit)
    frames = decode(folder / 'out' / 'picture.mp4', size) if code in (0, 1) else []
    covered = [bool(red_mask(frame).mean() > 0.05) for frame in frames]
    row = (report.get('layers') or [{}])[0]
    reasons = {span['reason'].split(' (')[0] for span in row.get('not_drawn', [])}
    record('spatial: a pin is drawn over its own source only: not under another source, not during a dissolve, '
           'and the notes say where and why',
           code == 1 and len(frames) == 35 and all(covered[:10]) and not any(covered[10:20])
           and all(covered[20:]) and reasons == {'another source is on screen',
                                                   'a dissolve or dip is on screen'}
           and 'another source is on screen (b)' in output and 'dissolve' in output
           and row.get('frames_by_cause') == {'drawn': 25, 'other_source': 5, 'dissolve': 5},
           f'{code} {covered} {reasons} ' + output[-400:])


def check_stale(record, tool, spatial, j, scripts_dir):
    """A layer whose source changed is stale: spatial.py check exits 1, a pin is not drawn, a blur stops."""
    folder = Path(j('spatial-stale'))
    folder.mkdir(parents=True, exist_ok=True)
    size = (320, 240)
    encode(folder / 'a.mp4', [np.full((240, 320), 128, np.uint8)] * 25, size)
    write_track(spatial, folder / 'a.mp4', folder / 'screen.json', [moving_quad(0, size)] * 25)
    code_before, _ = tool('spatial.py', 'check', folder / 'screen.json')
    encode(folder / 'a.mp4', [np.full((240, 320), 120, np.uint8)] * 30, size)
    code_after, output_check = tool('spatial.py', 'check', folder / 'screen.json')
    card(folder / 'red.png')
    edit = {'version': 1, 'size': list(size), 'fps': 25, 'sources': {'a': {'file': 'a.mp4'},
                                                                      'red': {'file': 'red.png'}},
            'picture': [{'src': 'a', 'in': 0.0, 'out': 1.0}], 'audio': [],
            'overlays': [{'kind': 'image', 'src': 'red', 'from': 0.0, 'to': 1.0, 'x': 0, 'y': 0, 'w': 0.2,
                          'pin': {'layer': 'screen.json'}}]}
    code_pin, output_pin, _ = render(tool, folder, edit)
    frames = decode(folder / 'out' / 'picture.mp4', size) if code_pin in (0, 1) else []
    blur = dict(edit, overlays=[{'kind': 'blur', 'region': {'layer': 'screen.json'}, 'from': 0.0, 'to': 1.0}])
    code_blur, output_blur, _ = render(tool, folder, blur, 'blur')
    record('spatial: a stale layer (its source changed) fails spatial.py check, is not pinned (with a note) and '
           'stops a blur',
           code_before == 0 and code_after == 1 and 'changed' in output_check and code_pin == 1
           and 'stale' in output_pin and frames and not any(red_mask(frame).any() for frame in frames)
           and code_blur == 2 and 'stale' in output_blur,
           f'{code_before} {code_after} {code_pin} {code_blur} ' + output_check[-200:] + output_pin[-200:])


def check_follow(record, tool, spatial, j):
    """A follow pin on a point track moves an overlay with the point, centred on it with an offset of zero."""
    folder = Path(j('spatial-follow'))
    folder.mkdir(parents=True, exist_ok=True)
    size = (320, 240)
    encode(folder / 'flat.mp4', [np.full((240, 320), 128, np.uint8)] * 25, size)
    points = [np.array([0.3 + 0.012 * index, 0.4 + 0.006 * index]) for index in range(25)]
    write_track(spatial, folder / 'flat.mp4', folder / 'dot.json', None, points=points)
    card(folder / 'red.png', size=(40, 40))
    edit = {'version': 1, 'size': list(size), 'fps': 25,
            'sources': {'a': {'file': 'flat.mp4'}, 'red': {'file': 'red.png'}},
            'picture': [{'src': 'a', 'in': 0.0, 'out': 1.0}], 'audio': [],
            'overlays': [{'kind': 'image', 'src': 'red', 'from': 0.0, 'to': 1.0, 'x': 0, 'y': 0, 'w': 0.125,
                          'pin': {'layer': 'dot.json', 'fit': 'follow', 'offset': [0, 0]}}]}
    code, output, _ = render(tool, folder, edit)
    frames = decode(folder / 'out' / 'picture.mp4', size) if code in (0, 1) else []
    worst = 0.0
    for index in (0, 12, 24):
        if index < len(frames):
            ys, xs = np.nonzero(red_mask(frames[index]))
            worst = max(worst, float(np.linalg.norm([xs.mean() + .5 - points[index][0] * 320,
                                                     ys.mean() + .5 - points[index][1] * 240])))
    record('spatial: a follow pin keeps an overlay centred on a point track (within 1 px)',
           code == 0 and len(frames) == 25 and worst < 1.0, f'{code} {worst:.2f} ' + output[-300:])


# ----------------------------------------------------------------------------------------------- tracking

def plane_clip(folder):
    """A 1280x720 textured plane moved by known homographies: visible (0-23), covered (24-29), visible (30-35), then
    leaving the frame fast (36-47). Returns the true corners per frame in displayed pixels."""
    tex = texture(480, 320, 1)
    background = texture(1280, 720, 2) * 0.35 + 80
    cover = texture(700, 560, 9)
    plane = np.array([[0, 0], [480, 0], [480, 320], [0, 320]], float)
    truth, frames = [], []
    for index in range(48):
        t = index / 47
        centre = np.array([400 + 380 * t, 300 + 60 * math.sin(t * 3)])
        if index >= 36:
            centre[0] += (index - 35) * 110
        angle = 0.25 * math.sin(t * 2.5)
        base = np.array([[-240, -160], [240, -160], [240, 160], [-240, 160]], float) * [1 + .2 * t,
                                                                                         .9 + .15 * math.cos(2 * t)]
        base[0, 0] += 30 * math.sin(2 * t)
        rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        corners = base @ rotation.T + centre
        rows, values = [], []
        for (x, y), (u, v) in zip(plane, corners):
            rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
            values += [u, v]
        matrix = np.append(np.linalg.solve(np.array(rows), np.array(values)), 1).reshape(3, 3)
        image = warp_plane(tex, background, matrix)
        if 24 <= index <= 29:
            x0, y0 = np.maximum(corners.min(axis=0).astype(int) - 30, 0)
            patch = image[y0:y0 + 560, x0:x0 + 700]
            patch[:] = cover[:patch.shape[0], :patch.shape[1]]
        frames.append(np.clip(np.round(image), 0, 255))
        truth.append(corners)
    encode(folder / 'plane.mp4', frames, (1280, 720), rate=24)
    return truth


def in_frame_share(quad, size):
    """Share of a quadrilateral's area inside the frame (sampled on a 40 x 40 grid of the plane)."""
    steps = (np.arange(40) + 0.5) / 40
    u, v = np.meshgrid(steps, steps)
    top = quad[0] + (quad[1] - quad[0]) * u[..., None]
    bottom = quad[3] + (quad[2] - quad[3]) * u[..., None]
    points = top + (bottom - top) * v[..., None]
    inside = (points[..., 0] >= 0) & (points[..., 0] < size[0]) & (points[..., 1] >= 0) & (points[..., 1] < size[1])
    return float(inside.mean())


def check_tracking(record, tool, j):
    """track.py follows a textured plane under known homographies within a pixel at 720p, and marks frames lost
    where it is covered or has left the frame, without inventing corners."""
    folder = Path(j('spatial-track'))
    folder.mkdir(parents=True, exist_ok=True)
    truth = plane_clip(folder)
    key = 10
    region = ','.join(f'{x:.3f},{y:.3f}' for x, y in truth[key])
    code, output = tool('track.py', folder / 'plane.mp4', '--at', f'{key / 24:.6f}', '--region', region,
                        '--name', 'plane', '--out', folder, '--from', '0', '--to', '2')
    layer = json.loads((folder / 'plane.json').read_text(encoding='utf-8')) if (folder / 'plane.json').is_file() \
        else {'frames': [], 'quality': {}}
    errors, lost = {}, []
    for index, frame in enumerate(layer['frames']):
        if frame['state'] == 'lost':
            lost.append(index)
        else:
            corners = np.array(frame['corners']) * [1280, 720]
            errors[index] = float(np.max(np.linalg.norm(corners - truth[index], axis=1)))
    shares = [in_frame_share(quad, (1280, 720)) for quad in truth]
    covered = set(range(24, 30))
    clear = [index for index in range(48) if index not in covered and shares[index] >= 0.5]
    gone = [index for index in range(48) if shares[index] < 0.15]
    worst = max((errors.get(index, 99.0) for index in clear), default=99.0)
    quality = layer['quality']
    record('spatial: track.py follows a textured plane within 1 px at 720p while at least half of it is in view, '
           'marks the covered frames lost and the frames where under 15% is in view lost, and measures drift',
           code == 1 and len(layer['frames']) == 48 and worst < 1.0 and covered <= set(lost)
           and set(gone) <= set(lost) and not set(lost) & set(clear) and quality.get('drift_px') is not None
           and quality['drift_px'] < 1.0,
           f'{code} worst {worst:.2f} lost {lost} gone {gone} drift {quality.get("drift_px")} ' + output[-300:])
    spatial = load(Path(__file__).resolve().parent.parent, 'spatial')
    plane = [[0, 0], [480, 0], [480, 320], [0, 320]]
    anchor = spatial.apply_homography(np.linalg.inv(spatial.homography(plane, truth[key])), [[520, 330]])
    code, output = tool('track.py', folder / 'plane.mp4', '--at', f'{key / 24:.6f}', '--point', '520,330',
                        '--name', 'point', '--out', folder, '--from', '0', '--to', '2')
    frames = json.loads((folder / 'point.json').read_text(encoding='utf-8'))['frames'] \
        if (folder / 'point.json').is_file() else []
    errors = {index: float(np.linalg.norm(np.array(frame['point']) * [1280, 720]
                                          - spatial.apply_homography(spatial.homography(plane, truth[index]),
                                                                     anchor)[0]))
              for index, frame in enumerate(frames) if frame['state'] != 'lost'}
    before = max((errors.get(index, 99.0) for index in range(24)), default=99.0)
    after = max((errors.get(index, 99.0) for index in range(30, 36)), default=99.0)
    record('spatial: a point track follows a point on a turning, scaling plane within 0.6 px, is lost while it is '
           'covered and is found again near its last place (within 1.5 px)',
           len(frames) == 48 and before < 0.6 and not set(range(24, 30)) & set(errors) and after < 1.5,
           f'{code} before {before:.2f} after {after:.2f} lost {[i for i in range(48) if i not in errors]} '
           + output[-200:])


def check_cut(record, tool, j):
    """A track stops at a shot change, even when the next shot shows a look-alike of the surface elsewhere."""
    folder = Path(j('spatial-cut'))
    folder.mkdir(parents=True, exist_ok=True)
    tex = texture(200, 130, 1)
    first, second = texture(640, 360, 2) * 0.35 + 80, texture(640, 360, 7) * 0.5 + 40
    frames, truth = [], []
    for index in range(32):
        background, x, y = (first, 120 + 4 * index, 90) if index < 16 else (second, 380, 200)
        corners = np.array([[x, y], [x + 200, y], [x + 200, y + 130], [x, y + 130]], float)
        matrix = np.array([[1, 0, x], [0, 1, y], [0, 0, 1]], float)
        frames.append(np.clip(np.round(warp_plane(tex, background, matrix)), 0, 255))
        truth.append(corners)
    encode(folder / 'cut.mp4', frames, (640, 360))
    region = ','.join(f'{value:.1f}' for value in truth[4].ravel())
    code, output = tool('track.py', folder / 'cut.mp4', '--at', '0.16', '--region', region, '--name', 'cut', '--out',
                        folder, '--from', '0', '--to', '2')
    layer = json.loads((folder / 'cut.json').read_text(encoding='utf-8')) if (folder / 'cut.json').is_file() else {}
    states = [frame['state'] for frame in layer.get('frames', [])]
    record('spatial: a track stops at a shot change and does not jump to a look-alike in the next shot',
           code == 1 and len(states) == 32 and all(state != 'lost' for state in states[:16])
           and all(state == 'lost' for state in states[16:]) and layer['quality'].get('shot_changes_s') == [0.64],
           f'{code} {"".join(state[0] for state in states)} {layer.get("quality", {}).get("shot_changes_s")} '
           + output[-300:])


def rotated_square_clip(folder):
    """A coded 320x180 clip of a bright square moving over texture, tagged to display rotated 90 degrees, with
    variable frame timing. Returns (path, displayed size)."""
    background = texture(320, 180, 4) * 0.4 + 30
    ys, xs = np.mgrid[0:56, 0:56]
    pattern = np.where(((xs // 7) + (ys // 7)) % 2, 250, 205)
    pattern[:4], pattern[-4:], pattern[:, :4], pattern[:, -4:] = 250, 250, 250, 250
    frames = []
    for index in range(40):
        image = background.copy()
        x, y = 70 + 3 * index, 50 + int(round(20 * math.sin(index / 7)))
        image[y:y + 56, x:x + 56] = pattern
        frames.append(image)
    plain = folder / 'square-cfr.mp4'
    timing = 'settb=1/1000,setpts=(N*40+if(mod(N\\,3)\\,9\\,0))/1000/TB'
    encode(plain, frames, (320, 180), before=['-vf', timing],
           after=['-fps_mode', 'passthrough', '-enc_time_base', '1/1000', '-video_track_timescale', '1000'])
    rotated = folder / 'square.mp4'
    tag = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-display_rotation', '90', '-i', str(plain), '-c', 'copy',
                          str(rotated)], capture_output=True)
    if tag.returncode:
        # FFmpeg before 6.0 has no -display_rotation; its rotate=90 tag writes the same display matrix (measured on
        # FFmpeg 5.1.2 and 9.0: both read back as rotation 90).
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(plain), '-c', 'copy', '-metadata:s:v:0', 'rotate=90',
                        str(rotated)], check=True)
    return rotated, (180, 320)


def square_truth(path, size):
    """The square's corners in each displayed frame (decoded by FFmpeg, autorotated), found by its brightness."""
    quads = []
    for frame in decode(path, size):
        ys, xs = np.nonzero(frame[..., 1] > 190)
        x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
        quads.append(np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], float))
    return quads


def check_rotation_vfr(record, tool, spatial, j, cv2_ok):
    """One run through rotation, variable frame timing, x1.5 and crop auto together: the layer is made on the
    displayed (autorotated) frame and the pinned overlay covers the square in every output frame."""
    folder = Path(j('spatial-rotation'))
    folder.mkdir(parents=True, exist_ok=True)
    source, size = rotated_square_clip(folder)
    truth = square_truth(source, size)
    block, displayed = spatial.bind_source(source, folder)
    times = spatial.source_frame_times(source, 0.0, 100.0, block['origin_s'])
    intervals = np.diff(times)
    timing_ok = displayed == [180, 320] and block['display']['rotation_degrees'] in (90, 270) and \
        float(intervals.max() - intervals.min()) > 0.01
    if cv2_ok:
        key = 5
        region = ','.join(f'{x:.2f},{y:.2f}' for x, y in truth[key])
        code, output = tool('track.py', source, '--at', f'{times[key]:.6f}', '--region', region, '--name', 'square',
                            '--out', folder, '--from', '0', '--to', '2')
        layer = json.loads((folder / 'square.json').read_text(encoding='utf-8'))
        errors = [float(np.max(np.linalg.norm(np.array(frame['corners']) * displayed - truth[index], axis=1)))
                  for index, frame in enumerate(layer['frames']) if frame['state'] != 'lost']
        tracked = len(errors) == len(truth) and max(errors) < 1.5
        detail = f'track {code} worst {max(errors) if errors else None} '
    else:
        write_track(spatial, source, folder / 'square.json', [quad / displayed for quad in truth])
        tracked, detail = True, 'OpenCV missing: layer built from measured geometry; '
    card(folder / 'red.png', size=(60, 60))
    edit = {'version': 1, 'size': [160, 160], 'fps': 25,
            'sources': {'a': {'file': 'square.mp4'}, 'red': {'file': 'red.png'}},
            'picture': [{'src': 'a', 'in': 0.1, 'out': 1.3, 'speed': 1.5, 'crop': {'path': 'auto'}}], 'audio': [],
            'overlays': [{'kind': 'image', 'src': 'red', 'from': 0.0, 'to': 0.8, 'x': 0, 'y': 0, 'w': 0.2,
                          'pin': {'layer': 'square.json', 'aspect': 'stretch'}}]}
    code, output, _ = render(tool, folder, edit)
    plain_code, _, _ = render(tool, folder, dict(edit, overlays=[]), 'plain')
    drawn = decode(folder / 'out' / 'picture.mp4', (160, 160)) if code in (0, 1) else []
    clean = decode(folder / 'plain' / 'picture.mp4', (160, 160)) if plain_code in (0, 1) else []
    worst, uncovered = 99.0, 1.0
    if drawn and clean:
        worst, uncovered = 0.0, 0.0
        for index in range(0, min(len(drawn), len(clean)), 4):
            square = clean[index][..., 1] > 190
            red = red_mask(drawn[index])
            if not square.any() or not red.any():
                worst = 99.0
                continue
            ys, xs = np.nonzero(square)
            ry, rx = np.nonzero(red)
            worst = max(worst, float(np.linalg.norm([xs.mean() - rx.mean(), ys.mean() - ry.mean()])))
            uncovered = max(uncovered, float((square & ~red).sum() / square.sum()))
    record('spatial: through a 90-degree rotation tag, variable frame timing, x1.5 and crop auto together, the '
           'layer is on the displayed frame and the pinned overlay covers the square (centre within 1.5 px)',
           timing_ok and tracked and code in (0, 1) and len(drawn) == 20 and worst < 1.5 and uncovered < 0.05,
           detail + f'{code} {len(drawn)} centre {worst:.2f} uncovered {uncovered:.3f} ' + output[-300:])


PAPER_EDIT = """---
title: Layers
size: 320x240
fps: 25
captions: none
---
- broll_01 0:00.00-0:01.00 The screen
  ~ still still_01 0.8 pin screen
  ~ title "Hello" 0.6 center behind nobody +0.2
- broll_02 0:00.00-0:00.60 Another shot
  ~ title "Wrong" 0.4 pin screen
- broll_01 0:00.00-0:00.80 The plate
  ~ blur plate
"""


def map_sources(tool, root, files):
    """Register files with map.py add: {file name: alias}."""
    aliases = {}
    for name, role in files:
        code, output = tool('map.py', 'add', root, root / name, '--role', role)
        aliases[name] = output.strip().split()[-1] if code == 0 else None
    return aliases


def check_paper_edit(record, tool, spatial, j, scripts_dir):
    """film.md reaches pin, behind and blur; cut.py check names a missing layer, a layer over the wrong source, lost
    frames under a blur and a stale layer, each with its line; render passes the fields and records the layers."""
    root = Path(j('spatial-project'))
    root.mkdir(parents=True, exist_ok=True)
    encode(root / 'screen.mp4', [np.full((240, 320), 128, np.uint8)] * 25, (320, 240))
    encode(root / 'other.mp4', [np.full((240, 320), 60, np.uint8)] * 25, (320, 240))
    card(root / 'logo.png')
    aliases = map_sources(tool, root, [('screen.mp4', 'broll'), ('other.mp4', 'broll'), ('logo.png', 'still')])
    states = {index: 'lost' for index in (3, 4)}
    quads = [moving_quad(index, (320, 240)) for index in range(25)]
    write_track(spatial, root / 'screen.mp4', root / 'spatial' / 'screen.json', quads, root=root)
    write_track(spatial, root / 'screen.mp4', root / 'spatial' / 'plate.json', quads, states, root=root)
    (root / 'film.md').write_text(PAPER_EDIT, encoding='utf-8')
    code, output = tool('cut.py', 'check', root, '--no-audio')
    found = {line: output.count(f'film.md:{line}: error') for line in (9, 11, 13)}
    record('spatial: cut.py check names a missing layer, a layer made from another source than the one on screen '
           'and lost frames under a blur, each on its own line with a suggestion',
           aliases == {'screen.mp4': 'broll_01', 'other.mp4': 'broll_02', 'logo.png': 'still_01'} and code == 1
           and found == {9: 1, 11: 1, 13: 1} and 'no layer spatial/nobody.json' in output
           and 'made from broll_01, but broll_02 is on screen' in output and 'lost on 2 frames' in output
           and 'render stops' in output, f'{code} {found} ' + output[-700:])
    layer = json.loads((root / 'spatial' / 'plate.json').read_text(encoding='utf-8'))
    layer['frames'][3] = layer['frames'][4] = {'state': 'tracked', 'corners': layer['frames'][2]['corners']}
    spatial.write_layer(root / 'spatial' / 'plate.json', layer)
    text = PAPER_EDIT.replace('  ~ title "Hello" 0.6 center behind nobody +0.2\n', '').replace(
        '  ~ title "Wrong" 0.4 pin screen\n', '')
    (root / 'film.md').write_text(text, encoding='utf-8')
    code, output = tool('cut.py', 'render', root)
    version = root / 'cuts' / 'v001'
    edit = json.loads((version / 'edit.json').read_text(encoding='utf-8')) if (version / 'edit.json').is_file() else {}
    manifest = json.loads((version / 'manifest.json').read_text(encoding='utf-8')) \
        if (version / 'manifest.json').is_file() else {}
    overlays = edit.get('overlays', [])
    pinned = [overlay for overlay in overlays if overlay.get('pin')]
    blurred = [overlay for overlay in overlays if overlay.get('kind') == 'blur']
    records = {row.get('sidecar'): row for row in manifest.get('layers') or []}
    record('spatial: cut.py render passes pin and blur to edit.json (layer paths from the version), binds the '
           'source by the map\'s identity and records each layer\'s sidecar SHA-256 in the manifest',
           code in (0, 1) and len(pinned) == 1 and pinned[0]['pin'] == {'layer': '../../spatial/screen.json',
                                                                        'fit': 'corners'}
           and len(blurred) == 1 and blurred[0]['region']['layer'] == '../../spatial/plate.json'
           and edit['sources']['broll_01'].get('sha256') == spatial.sha256_of(root / 'screen.mp4')
           and records.get('spatial/screen.json', {}).get('sidecar_sha256') == spatial.sha256_of(
               root / 'spatial' / 'screen.json') and 'spatial/plate.json' in records
           and not list(version.rglob('*.mkv')), f'{code} {overlays} {manifest.get("layers")} ' + output[-400:])
    # The version's checks list its layers as inputs, so a layer made again later makes them out of date.
    tool('check.py', root, '--no-speech')
    checks = version / 'checks.json'
    rows = json.loads(checks.read_text(encoding='utf-8')).get('inputs', []) if checks.is_file() else []
    fresh_code, _ = tool('check.py', '--verify', checks)
    layer = json.loads((root / 'spatial' / 'screen.json').read_text(encoding='utf-8'))
    layer['quality'] = dict(layer.get('quality') or {}, note='tracked again')
    spatial.write_layer(root / 'spatial' / 'screen.json', layer)
    stale_code, stale_out = tool('check.py', '--verify', checks)
    record('spatial: a version\'s checks list the layers it draws as inputs, and --verify says a re-made layer '
           'makes them out of date',
           any(row.get('role') == 'layer' for row in rows) and fresh_code == 0 and stale_code == 1,
           f'{fresh_code} {stale_code} {[row.get("role") for row in rows]} ' + stale_out[-300:])
    encode(root / 'screen.mp4', [np.full((240, 320), 140, np.uint8)] * 30, (320, 240))
    code, output = tool('cut.py', 'check', root, '--no-audio')
    record('spatial: cut.py check reports a layer whose source changed since it was mapped as stale, on its line',
           code == 1 and 'film.md:8: error: layer screen is stale' in output and 'film.md:11: error' in output,
           f'{code} ' + output[-500:])


def check_track_without_opencv(record, scripts_dir, j):
    """Without OpenCV, track.py exits 2 and says how to install it."""
    track = load(scripts_dir, 'track')
    saved = sys.modules.get('cv2', None)
    present = 'cv2' in sys.modules
    sys.modules['cv2'] = None
    stream = io.StringIO()
    try:
        with contextlib.redirect_stderr(stream):
            code = track.main(['missing.mp4', '--at', '0', '--point', '1,1', '--name', 'x', '--out', j('none')])
    finally:
        if present:
            sys.modules['cv2'] = saved
        else:
            del sys.modules['cv2']
    record('spatial: track.py without OpenCV exits 2 with the install message',
           code == 2 and 'missing' in stream.getvalue() and 'Fix:' in stream.getvalue(), stream.getvalue()[-200:])


def check_cli(record, tool, spatial, j):
    """spatial.py show and check: a current layer passes; a layer missing a frame fails check with the time."""
    folder = Path(j('spatial-cli'))
    folder.mkdir(parents=True, exist_ok=True)
    encode(folder / 'a.mp4', [np.full((120, 160), 90, np.uint8)] * 10, (160, 120))
    write_track(spatial, folder / 'a.mp4', folder / 'ok.json', [moving_quad(index, (160, 120)) for index in range(10)])
    show_code, shown = tool('spatial.py', 'show', folder / 'ok.json')
    check_code, _ = tool('spatial.py', 'check', folder / 'ok.json')
    layer = json.loads((folder / 'ok.json').read_text(encoding='utf-8'))
    del layer['times'][4]
    del layer['frames'][4]
    (folder / 'gap.json').write_text(json.dumps(layer), encoding='utf-8')
    gap_code, gap = tool('spatial.py', 'check', folder / 'gap.json')
    record('spatial: show describes a current layer; check passes it and fails a layer missing a source frame, '
           'naming the time',
           show_code == 0 and 'current' in shown and check_code == 0 and gap_code == 1 and '0.160' in gap,
           f'{show_code} {check_code} {gap_code} ' + gap[-300:])


def run_spatial_cases(tool, record, j, scripts_dir):
    """Every spatial case; tracking cases need OpenCV."""
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        print('skipped: spatial cases need FFmpeg and ffprobe', flush=True)
        return
    spatial = load(scripts_dir, 'spatial')
    cv2_ok = have_cv2()
    check_contract(record, spatial, j)
    check_cli(record, tool, spatial, j)
    check_pin(record, tool, spatial, j)
    check_follow(record, tool, spatial, j)
    check_behind(record, tool, spatial, j, scripts_dir)
    check_swapped_matte(record, tool, spatial, j)
    check_blur(record, tool, spatial, j)
    check_wrong_source(record, tool, spatial, j)
    check_stale(record, tool, spatial, j, scripts_dir)
    check_track_without_opencv(record, scripts_dir, j)
    check_paper_edit(record, tool, spatial, j, scripts_dir)
    check_rotation_vfr(record, tool, spatial, j, cv2_ok)
    if cv2_ok:
        check_tracking(record, tool, j)
        check_cut(record, tool, j)
    else:
        print('skipped: track.py accuracy needs OpenCV (setup.py --install spatial)', flush=True)

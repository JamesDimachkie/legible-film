"""Known-answer tests for coherent flash area and moving high-contrast type."""
import importlib.util
import json
import math
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def load_script(scripts_dir, name):
    """Load the scanner or checker from the skill being tested."""
    spec = importlib.util.spec_from_file_location('flash_case_' + name, Path(scripts_dir) / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encode(path, images, fps):
    """Encode RGB fixtures losslessly so the area boundary is measurable."""
    height, width = images[0].shape[:2]
    command = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s',
               f'{width}x{height}', '-r', str(fps), '-i', 'pipe:0', '-c:v', 'ffv1', '-pix_fmt', 'bgr0', str(path)]
    result = subprocess.run(command, input=b''.join(image.tobytes() for image in images), capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace')[-500:])


def text_mask():
    """Make a reproducible word mark from Pillow's bundled bitmap font."""
    image = Image.new('L', (112, 20), 0)
    ImageDraw.Draw(image).text((0, 0), 'ATLAS FOLD', fill=255, font=ImageFont.load_default())
    box = image.getbbox()
    image = image.crop(box)
    nearest = getattr(Image, 'Resampling', Image).NEAREST
    return image.resize((480, 99), nearest)


def drifting_text():
    """A pale end card moves by less than one analysis pixel repeatedly."""
    mask = text_mask()
    frames = []
    for frame in range(72):
        x = 48 + round(math.sin(frame * 2 * math.pi / 12))
        image = Image.new('RGB', (576, 324), (240, 240, 240))
        image.paste((8, 8, 8), (x, 112), mask)
        frames.append(np.asarray(image).copy())
    return frames


def zooming_text():
    """Large bright type recedes in one continuous movement, with no blinking."""
    mask = text_mask()
    lanczos = getattr(Image, 'Resampling', Image).LANCZOS
    frames = []
    for frame in range(72):
        factor = 1.18 - .85 * frame / 71
        size = (max(1, round(mask.width * factor)), max(1, round(mask.height * factor)))
        word = mask.resize(size, lanczos)
        image = Image.new('RGB', (576, 324), (8, 8, 8))
        image.paste((245, 245, 245), ((576 - size[0]) // 2, (324 - size[1]) // 2), word)
        frames.append(np.asarray(image).copy())
    return frames


def threshold_flash(pixel_delta, red=False, moving_content=False):
    """A quarter-window flash on low-contrast moving texture, or a flash moving with it."""
    rng = np.random.default_rng(716)
    background = rng.integers(18, 70, (108, 192), dtype=np.uint8)
    mask = np.zeros((108, 192), dtype=bool)
    if moving_content:
        mask[36:56, 64:102] = True
    else:
        mask[36:54, 64:96] = True
        if pixel_delta > 0:
            mask[36, 96] = True
        elif pixel_delta < 0:
            mask[36, 64] = False
    frames = []
    for frame in range(72):
        image = np.repeat(background[:, :, None], 3, axis=2)
        if (frame // 3) % 2:
            image[mask] = (255, 0, 0) if red else (245, 245, 245)
        shift = frame // 6 if moving_content else frame
        if moving_content:
            image = np.roll(image, shift, axis=1)
        else:
            moved = np.roll(background, shift, axis=0)
            image[~mask] = np.repeat(moved[:, :, None], 3, axis=2)[~mask]
        frames.append(image)
    return frames


def ambiguous_flash():
    """A threshold flash over high-contrast moving checks stays a review candidate."""
    yy, xx = np.indices((108, 192))
    base = ((xx // 8 + yy // 8) % 2 * 245).astype(np.uint8)
    frames = []
    for frame in range(72):
        phase = (frame // 3) % 2
        texture = np.roll(base, phase * 8, axis=1)
        image = np.repeat(texture[:, :, None], 3, axis=2)
        image[36:54, 64:96] = 245 if phase else 0
        image[36, 96] = 245 if phase else 0
        frames.append(image)
    return frames


def relay_strips(light=235, dark=20):
    """Three strips, each a third of the centre window, flip one at a time every 3 frames at 24 fps.

    Consecutive swings never share pixels, but each strip reverses 9 frames later in the same place, so the field
    holds 8 transitions a second of a third of its area: a flash by WCAG's count that adjacent pairing would miss."""
    edges = [(192, 255), (255, 318), (318, 384)]
    state = [light, dark, light]
    frames = []
    for frame in range(72):
        if frame and frame % 3 == 0:
            strip = (frame // 3 - 1) % 3
            state[strip] = dark if state[strip] == light else light
        image = np.full((324, 576, 3), 128, dtype=np.uint8)
        for (left, right), value in zip(edges, state):
            image[:, left:right] = value
        frames.append(image)
    return frames


def texture(seed=3):
    """Low-contrast blocks twice the frame's width, for a scene that pans."""
    rng = np.random.default_rng(seed)
    small = rng.integers(60, 150, (324 // 12 + 1, 1152 // 12 + 1), dtype=np.uint8)
    return np.kron(small, np.ones((12, 12), dtype=np.uint8))[:324, :1152]


def strobe(pan=3, jitter=0, red=False):
    """A block over 40% of the centre window strobes at 4 Hz (24 fps) while the scene pans or the block jumps."""
    scene = texture()
    frames = []
    for frame in range(72):
        image = np.repeat(scene[:, pan * frame:pan * frame + 576, None], 3, axis=2).copy()
        if (frame // 3) % 2:
            left = 210 + jitter * ((frame // 6) % 3 - 1)
            image[120:200, left:left + 156] = (255, 0, 0) if red else (250, 250, 250)
        frames.append(image)
    return frames


def scroll_text():
    """Dense dark lines of small type on white scroll up 6 px a frame: motion, and no place flashes."""
    font = ImageFont.load_default()
    page = Image.new('L', (576, 1296), 245)
    draw = ImageDraw.Draw(page)
    line = 'lines of small body copy scroll upward through the window at a steady reading pace '
    for row in range(0, 1296, 14):
        draw.text((8, row), (line * 2)[:96], fill=10, font=font)
    nearest = getattr(Image, 'Resampling', Image).NEAREST
    page = np.asarray(page.resize((576, 2592), nearest).crop((0, 0, 576, 1296)))
    return [np.repeat(page[6 * frame:6 * frame + 324, :, None], 3, axis=2) for frame in range(72)]


def slide_bars():
    """Three wide dark bars slide left across a light ground at 9 px a frame, each crossing once."""
    frames = []
    for frame in range(72):
        image = np.full((324, 576, 3), 235, dtype=np.uint8)
        for bar in range(3):
            left = 616 + bar * 260 - 9 * frame
            image[60:264, max(0, left):max(0, min(576, left + 150))] = 25
        frames.append(image)
    return frames


def staged_crossfade():
    """The left half darkens and the right half brightens in alternating steps of about 0.15 relative luminance.

    Each step moves half of a centre window one way, so swings alternate direction, but no pixel ever reverses:
    nothing flashes. Counting swings without asking whether the same pixels go back finds 10 in under half a
    second; a same-place reading finds none and leaves the swings for review."""
    darkening = [225, 204, 179, 149, 108, 39]
    brightening = darkening[::-1]
    frames = []
    for frame in range(72):
        steps = min(max(frame - 11, 0), 10)
        image = np.empty((324, 576, 3), dtype=np.uint8)
        image[:, :288] = darkening[(steps + 1) // 2]
        image[:, 288:] = brightening[steps // 2]
        frames.append(image)
    return frames


def check_media(tool, record, j, name, frames, expected, red=False, candidate=False, fps=30):
    """Compare the actual definite flash result, retaining pattern-only inspection prompts."""
    path = Path(j(name + '.mkv'))
    report_path = Path(j(name + '.json'))
    try:
        encode(path, frames, fps)
    except (OSError, RuntimeError) as error:
        record('flash: ' + name, False, str(error))
        return
    if report_path.exists():
        report_path.unlink()
    code, output = tool('flash_scan.py', path, '--json', report_path)
    data = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    flagged = data.get('flagged', [])
    classic = max((row['classic_max_per_s'] for row in flagged), default=0)
    red_count = max((row['red_max_per_s'] for row in flagged), default=0)
    definite = classic > 6 or red_count > 6
    valid = report_path.is_file() and isinstance(data.get('flagged'), list) and 'verdict' in data
    ok = (valid and code == (1 if flagged else 0) and definite == expected and (not red or red_count > 6)
          and (not candidate or code == 1))
    record('flash: ' + name, ok, f'expected definite={expected}, classic={classic}, red={red_count}; {output[-200:]}')


def check_area_boundary(record, scripts_dir):
    """Treat exactly a quarter conservatively; test one pixel either side in both channels."""
    scanner = load_script(scripts_dir, 'flash_scan')
    if not hasattr(scanner, 'CoherentZig'):
        record('flash: coherent area and direction boundaries', False, 'coherent classic detector is absent')
        return
    results = {}
    for count in (2499, 2500, 2501):
        for red in (False, True):
            detector = scanner.RedZig() if red else scanner.CoherentZig()
            for frame in range(30):
                pixels = np.zeros(10000, dtype=np.float32)
                if frame % 2:
                    pixels[:count] = 100 if red else .5
                detector.push(frame / 30, pixels)
            detector.finish()
            results[(count, red)] = scanner.busiest_second(detector.ends)[0]
    for count in (2499, 2500, 2501):
        for red in (False, True):
            observed = results[(count, red)]
            record(f'flash: {count}/10000 pixels ' + ('red' if red else 'general'),
                   (observed > 6) == (count >= 2500), f'count={observed}')
    for red in (False, True):
        detector = scanner.RedZig() if red else scanner.CoherentZig()
        pivot = np.zeros(10000, dtype=np.float32)
        first = pivot.copy()
        first[:2500] = 30 if red else .12
        later = np.full(10000, 19 if red else .09, dtype=np.float32)
        later[:2499] = 100 if red else .8
        detector.push(0, pivot)
        detector.push(1, first)
        detector.push(2, later)
        record('flash: peak refinement preserves the qualifying ' + ('red' if red else 'general') + ' area',
               detector.changed(detector.pivot, detector.extreme, detector.direction))
    detector = scanner.CoherentZig()
    for frame in range(30):
        pixels = np.full(10000, .3, dtype=np.float32)
        if frame % 2:
            pixels[:2000] = .8
            pixels[2000:4000] = 0
        detector.push(frame / 30, pixels)
    detector.finish()
    count = scanner.busiest_second(detector.ends)[0]
    record('flash: opposite directions do not combine into a classic transition', count <= 6, str(count))
    detector = scanner.CoherentZig()
    for frame in range(30):
        pixels = np.full(10000, .3, dtype=np.float32)
        if frame % 2:
            pixels[:3000] = .8
            pixels[3000:6000] = 0
        detector.push(frame / 30, pixels)
    detector.finish()
    definite = scanner.busiest_second(detector.ends)[0]
    candidate = scanner.busiest_second(detector.ends + detector.ambiguous_ends)[0]
    record('flash: simultaneous opposing quarter-area swings stay a pattern candidate',
           definite <= 6 and candidate > 6, f'classic={definite} candidate={candidate}')
    # Swings that alternate direction on different pixels: half the pixels step darker, then the other half step
    # brighter, and no pixel ever goes back. They are not flashes, and they stay visible for review.
    detector = scanner.CoherentZig()
    pixels = np.concatenate([np.full(5000, .75, dtype=np.float32), np.full(5000, .02, dtype=np.float32)])
    detector.push(0, pixels.copy())
    for step in range(1, 11):
        if step % 2:
            pixels[:5000] -= .146
        else:
            pixels[5000:] += .146
        detector.push(step / 30, pixels.copy())
    detector.finish()
    counted = scanner.busiest_second(detector.ends)[0]
    unreversed = scanner.busiest_second(getattr(detector, 'coherent_ends', []))[0]
    record('flash: swings no opposite swing reverses in the same pixels are kept for review, not counted',
           counted <= 6 and unreversed > 6, f'counted={counted} unreversed={unreversed}')
    detector = scanner.CoherentZig()
    pixels = np.full(9000, .5, dtype=np.float32)
    strips = [slice(0, 3000), slice(3000, 6000), slice(6000, 9000)]
    levels = [.9, .05, .9]
    pixels[strips[1]] = .05
    pixels[strips[0]] = pixels[strips[2]] = .9
    for frame in range(30):
        if frame and frame % 3 == 0:
            strip = (frame // 3 - 1) % 3
            levels[strip] = .05 if levels[strip] == .9 else .9
            pixels[strips[strip]] = levels[strip]
        detector.push(frame / 24, pixels.copy())
    detector.finish()
    counted = scanner.busiest_second(detector.ends)[0]
    record('flash: a relay whose consecutive swings never share pixels is still counted', counted > 6,
           f'counted={counted}')
    for changed in (2499, 2500):
        detector = scanner.GeneralZig()
        for frame in range(30):
            pixels = np.full(10000, .3, dtype=np.float32)
            if frame % 2:
                pixels[:changed // 2] = .8
                pixels[changed // 2:changed] = 0
            detector.push(frame / 30, pixels)
        detector.finish()
        count = scanner.busiest_second(detector.ends)[0]
        record(f'flash: {changed}/10000 mixed-direction pixels remain a pattern candidate at the boundary',
               (count > 6) == (changed >= 2500), str(count))


def run_flash_cases(tool, record, j, scripts_dir, skip=None):
    """Screen false-positive motion and threshold-area flashes, plus the repository showcase."""
    check_area_boundary(record, scripts_dir)
    check_media(tool, record, j, 'subpixel-drifting-text', drifting_text(), False)
    check_media(tool, record, j, 'large-text-recedes', zooming_text(), False)
    check_media(tool, record, j, 'below-quarter-moving-texture', threshold_flash(-1), False)
    check_media(tool, record, j, 'quarter-moving-texture', threshold_flash(0), True)
    check_media(tool, record, j, 'red-quarter-moving-texture', threshold_flash(0, red=True), True, red=True)
    check_media(tool, record, j, 'above-quarter-moving-texture', threshold_flash(1), True)
    check_media(tool, record, j, 'red-above-quarter-moving-texture', threshold_flash(1, red=True), True, red=True)
    check_media(tool, record, j, 'flash-in-moving-content', threshold_flash(1, moving_content=True), True)
    check_media(tool, record, j, 'flash-over-moving-checks', ambiguous_flash(), False, candidate=True)
    # A flash is a change and its reversal in the same place. Real strobes still fail, including relays whose
    # consecutive swings never share pixels; motion and swings nothing reverses never fail, and the unreversed
    # swings stay a look rather than a silent pass.
    check_media(tool, record, j, 'relay-3-strips', relay_strips(), True, fps=24)
    check_media(tool, record, j, 'relay-3-strips-low-contrast', relay_strips(179, 137), True, fps=24)
    check_media(tool, record, j, 'strobe-in-panning-scene', strobe(), True, fps=24)
    check_media(tool, record, j, 'strobe-jumping-block', strobe(pan=0, jitter=12), True, fps=24)
    check_media(tool, record, j, 'red-strobe-in-panning-scene', strobe(red=True), True, red=True, fps=24)
    check_media(tool, record, j, 'scrolling-text', scroll_text(), False, fps=24)
    check_media(tool, record, j, 'sliding-bars', slide_bars(), False, fps=24)
    check_media(tool, record, j, 'staged-crossfade-never-reverses', staged_crossfade(), False, candidate=True,
                fps=24)
    repository = Path(scripts_dir).resolve().parents[2]
    showcase = repository / '.github' / 'media' / 'atlasfold-showcase.mp4'
    # The showcase ships with a checkout of the repository, not with an installed skill: missing from a checkout it
    # is a failure; missing from an installation it is a counted skip.
    checkout = (repository / '.github' / 'workflows' / 'ci.yml').is_file() and (repository / '.claude-plugin').is_dir()
    if not showcase.is_file():
        if checkout:
            record('flash: repository showcase has no definite flash failure', False, f'missing {showcase}')
        elif skip:
            skip('flash: repository showcase has no definite flash failure',
                 'an installed skill does not include the repository showcase')
        else:
            print('SKIP  flash: repository showcase (an installed skill does not include the repository showcase)')
        return
    report = Path(j('showcase.json'))
    if report.exists():
        report.unlink()
    code, output = tool('flash_scan.py', showcase, '--json', report)
    data = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
    check = load_script(scripts_dir, 'check')
    item = check.flash_item(data)
    valid = report.is_file() and isinstance(data.get('flagged'), list) and 'verdict' in data
    record('flash: repository showcase has no definite flash failure',
           valid and code == (1 if data['flagged'] else 0) and item['state'] in ('pass', 'look'),
           f'{item}; {output[-200:]}')

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


def check_media(tool, record, j, name, frames, expected, red=False, candidate=False):
    """Compare the actual definite flash result, retaining pattern-only inspection prompts."""
    path = Path(j(name + '.mkv'))
    report_path = Path(j(name + '.json'))
    try:
        encode(path, frames, 30)
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


def run_flash_cases(tool, record, j, scripts_dir):
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
    showcase = Path(scripts_dir).resolve().parents[2] / '.github' / 'media' / 'atlasfold-showcase.mp4'
    if not showcase.is_file():
        record('flash: repository showcase has no definite flash failure', False, f'missing {showcase}')
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

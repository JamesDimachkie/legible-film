"""Synthetic streaming-render regressions; these do not judge a finished film."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path


def hashes(path):
    """Return hashes of each decoded RGB output frame."""
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-fps_mode', 'passthrough',
                             '-pix_fmt', 'rgb24', '-f', 'framemd5', '-'], capture_output=True, check=True, text=True)
    return [line.split(',')[-1].strip() for line in result.stdout.splitlines()
            if line and not line.startswith('#')]


def old_spool_reference(record, root, source, scripts_dir):
    """Compare streamed rendering with frames decoded to files as the earlier renderer did."""
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location('stream_test_assemble', Path(scripts_dir) / 'assemble.py')
        assemble = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(assemble)
    finally:
        sys.dont_write_bytecode = previous_bytecode
    motion_available = assemble.has_filter('ffmpeg', 'minterpolate') and assemble.has_filter('ffmpeg', 'tpad')
    if not motion_available:
        print('SKIP stream motion reference: FFmpeg minterpolate or tpad is unavailable', flush=True)
    edit = {'version': 1, 'size': [96, 64], 'fps': 12, 'sources': {'a': {'file': str(source)}},
            'picture': [{'src': 'a', 'in': 0, 'out': 1.5},
                        {'src': 'a', 'in': 2, 'out': 3.5, 'speed': .7, 'retime': 'blend',
                         'join': {'kind': 'dissolve', 'dur': .25}},
                        {'src': 'a', 'in': 0, 'out': 1, 'speed': .5,
                         'retime': 'motion' if motion_available else 'blend',
                         'join': {'kind': 'dip', 'dur': .2}},
                        {'src': 'a', 'in': 1, 'out': 1.5, 'hold_previous': True}]}
    cache, properties, used = assemble.conform('ffmpeg', 'ffprobe', edit, root, root, 1024 ** 3, [])
    clips, _, _, _, _ = assemble.plan_picture(edit, root, cache, 'ffmpeg', 'ffprobe', root, [])
    assemble.motion_retimes('ffmpeg', clips, properties, 12, root, 1024 ** 3, used)
    decoders = [entry[0] for entry in cache.values()]
    decoders.extend(clip['motion_raw'] for clip in clips if clip['mode'] == 'motion')
    record('stream: source and motion decoders each use one input thread',
           all(any(option == '-threads' and value == '1' for option, value in
                   zip(decoder.options, decoder.options[1:])) for decoder in decoders))
    legacy = []
    expected_bytes = 0
    timestamps_match = True
    for number, clip in enumerate(clips):
        copy = dict(clip)
        for field in ('raw', 'motion_raw'):
            if field not in clip:
                continue
            decoder = clip[field]
            path = root / f'old-{number}-{field}.rgb'
            reader = assemble.Frames(decoder.ffmpeg, decoder.filename, decoder.vf, decoder.size, decoder.options)
            count = 0
            with path.open('wb') as output:
                for raw in reader:
                    output.write(raw)
                    count += 1
                    expected_bytes += len(raw)
            timestamps_match = timestamps_match and reader.times(count) == decoder.times
            copy[field] = str(path)
        legacy.append(copy)
    total = clips[-1]['at'] + clips[-1]['duration']
    old = root / 'old-picture.mp4'
    new = root / 'new-picture.mp4'
    old_count = assemble.render_picture('ffmpeg', legacy, [], 96, 64, 12, total, str(old))
    new_count = assemble.render_picture('ffmpeg', clips, [], 96, 64, 12, total, str(new))
    old_hashes, new_hashes = hashes(old), hashes(new)
    modes = 'blend, motion' if motion_available else 'blend'
    record(f'stream: RGB hashes match the old file-spool reference through {modes}, joins and hold',
           timestamps_match and expected_bytes > 0 and old_count == new_count == len(old_hashes)
           and old_hashes == new_hashes, f'frames {old_count}/{new_count}; timestamps match {timestamps_match}')

    class HashEncoder:
        """Capture the exact RGB bytes sent to the encoder without encoding them."""
        frames = []

        def __init__(self, *args):
            """Start a new capture."""
            HashEncoder.frames = []

        def write(self, frame):
            """Hash one RGB frame before encoding."""
            HashEncoder.frames.append(hashlib.sha256(frame.tobytes()).hexdigest())

        def close(self):
            """Finish a capture without an encoder process."""
            pass

        def abort(self):
            """Abort a capture without an encoder process."""
            pass

    original_encoder = assemble.Encoder
    try:
        assemble.Encoder = HashEncoder
        assemble.render_picture('ffmpeg', legacy, [], 96, 64, 12, total, str(old))
        old_pixels = list(HashEncoder.frames)
        assemble.render_picture('ffmpeg', clips, [], 96, 64, 12, total, str(new))
        new_pixels = list(HashEncoder.frames)
    finally:
        assemble.Encoder = original_encoder
    record('stream: every pre-encode RGB frame matches the old-spool reference',
           len(old_pixels) == old_count and old_pixels == new_pixels,
           f'{len(old_pixels)} old frames, {len(new_pixels)} streamed frames')

    real_frames = assemble.Frames
    retry_source = cache[0][0]
    original_options = retry_source.options
    retry_source.options = [original_options[0], '-ss', '0', *original_options[1:]]
    failures = []

    class FailPlaybackOnce:
        """Fail a seeked playback after frames have already reached the compositor."""

        def __init__(self, ffmpeg, filename, vf, size, options, timestamps_only=False):
            """Wrap the real decoder and choose exactly one seeked playback to interrupt."""
            self.real = real_frames(ffmpeg, filename, vf, size, options, timestamps_only=timestamps_only)
            self.fail = not timestamps_only and '-ss' in options and not failures
            self.failed = False

        def __iter__(self):
            """Stop the injected decoder after three frames; all other decoders remain real."""
            for number, raw in enumerate(self.real):
                if self.fail and number == 3:
                    self.real.proc.kill()
                    self.real.proc.stdout.close()
                    self.real.proc.wait()
                    self.real.reader.join()
                    self.failed = True
                    failures.append(True)
                    return
                yield raw

        def times(self, count):
            """Expose the injected failure through the normal decoder status check."""
            if self.failed:
                raise RuntimeError('injected seeked playback failure')
            return self.real.times(count)

        def scan(self):
            """Scan the linear retry with the real decoder."""
            return self.real.scan()

        def __getattr__(self, name):
            """Expose the real process and timestamp state for cleanup."""
            return getattr(self.real, name)

    try:
        assemble.Frames = FailPlaybackOnce
        assemble.Encoder = HashEncoder
        retried_count, retried_layers = assemble.render_picture_with_retry(
            'ffmpeg', clips, [], 96, 64, 12, total, str(new))
        retried_pixels = list(HashEncoder.frames)
        retried_without_seek = '-ss' not in retry_source.options
    finally:
        assemble.Frames = real_frames
        assemble.Encoder = original_encoder
        retry_source.options = original_options
    record('stream: seeked playback failure restarts the picture with exact linear-decoded frames',
           len(failures) == 1 and retried_without_seek and retried_layers is None and retried_count == old_count
           and retried_pixels == old_pixels, f'{len(retried_pixels)} retried frames')

    class ChangedClock:
        """Give a linear retry a different clock without opening a real decoder."""

        def __init__(self, *args, **kwargs):
            """Accept the normal decoder arguments."""
            pass

        def scan(self):
            """Return a different clock so the partial render cannot be accepted."""
            return [-1.0]

    changed_retry = assemble.FrameSource('ffmpeg', str(source), '', 1, ['-ss', '1', '-t', '2'], [0.0])
    try:
        assemble.Frames = ChangedClock
        try:
            changed_retry.retry_without_seek()
            refused_retry = False
        except ValueError as error:
            refused_retry = 'linear retry timestamps changed' in str(error)
    finally:
        assemble.Frames = real_frames
    record('stream: a linear retry with a changed clock fails instead of accepting a partial render',
           refused_retry and '-ss' in changed_retry.options)

    decoder = cache[0][0]
    window = decoder.open()
    first = window.frame(0)
    second = window.frame(1)
    repeated = window.frame(0)
    later = window.frame(3)
    bounded = len(window.frames) <= 2
    window.close()
    with (root / 'old-0-raw.rgb').open('rb') as reference:
        expected = [reference.read(decoder.size) for _ in range(4)]
    record('stream: forward reader keeps two frames and preserves blend lookahead',
           bounded and [first, second, repeated, later] == [expected[0], expected[1], expected[0], expected[3]])

    changed_times = list(decoder.times)
    changed_times[-1] += .01
    changed = assemble.FrameSource(decoder.ffmpeg, decoder.filename, decoder.vf, decoder.size, decoder.options,
                                   changed_times).open()
    changed.frame(0)
    try:
        changed.close()
        refused = False
    except ValueError as error:
        refused = 'playback timestamps changed' in str(error)
    record('stream: a playback decode that differs from the planned clock is refused', refused)

    real_frames = assemble.Frames
    real_before = assemble.presentation_frame_before
    attempts = []

    class FailSeekOnce:
        """Inject a failed seek while allowing the retry to use the real decoder."""

        def __init__(self, ffmpeg, filename, vf, size, options, timestamps_only=False):
            """Prepare the injected seek failure or the real unseeked retry."""
            self.seek = '-ss' in options
            attempts.append(self.seek)
            self.real = None if self.seek else real_frames(ffmpeg, filename, vf, size, options,
                                                           timestamps_only=timestamps_only)

        def scan(self):
            """Fail the first seek and otherwise scan normally."""
            if self.seek:
                raise RuntimeError('injected seek failure')
            return self.real.scan()

        def end(self):
            """Return the real unseeked decoder's final presentation time."""
            return self.real.end()

    retry_edit = {'size': [96, 64], 'sources': {'a': {'file': str(source)}},
                  'picture': [{'src': 'a', 'in': 1, 'out': 2}]}
    try:
        assemble.Frames = FailSeekOnce
        assemble.presentation_frame_before = lambda *args, **kwargs: (1.0, .25)
        _, retry_properties, _ = assemble.conform('ffmpeg', 'ffprobe', retry_edit, root, root, 100, [])
    finally:
        assemble.Frames = real_frames
        assemble.presentation_frame_before = real_before
    # conform keys properties by the resolved path (a Windows runner's temp folder is an 8.3 short name), as here.
    key = assemble.source_path(root, retry_edit['sources'], 'a')
    record('stream: a failed seek retries the timestamp decode without seeking',
           attempts == [True, False] and retry_properties.get(key, {}).get('decode_seek_s') == 0,
           f'{attempts} {sorted(retry_properties)}')

    spec = importlib.util.spec_from_file_location('stream_test_cut', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    record('stream: the cut guard reserves no raw RGB spool for a 4K motion clip',
           cut.estimate_spool({'picture': [{'src': 'a', 'in': 0, 'out': 180, 'retime': 'motion'}]},
                              {'size': [3840, 2160], 'fps': 30}, None, {}) == 0)


def bounded_disk_case(tool, record, root):
    """Measure the output directory while a source many times larger than the bound is rendered."""
    source = root / 'long-source.mkv'
    result = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi',
                             '-i', 'testsrc2=s=96x64:r=12:d=12', '-c:v', 'ffv1', '-threads', '1', str(source)],
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace'))
    output_dir = root / 'bounded-output'
    output_dir.mkdir(exist_ok=True)
    edit = {'version': 1, 'size': [96, 64], 'fps': 12, 'sources': {'a': {'file': str(source)}},
            'picture': [{'src': 'a', 'in': 0, 'out': 12}]}
    edit_path = output_dir / 'edit.json'
    edit_path.write_text(json.dumps(edit), encoding='utf-8')
    peak = [0]
    done = threading.Event()

    def observe():
        """Sample only the explicitly created output directory, including temporary files."""
        while not done.is_set():
            size = 0
            for folder, _, files in os.walk(output_dir):
                for name in files:
                    try:
                        size += (Path(folder) / name).stat().st_size
                    except FileNotFoundError:
                        pass
            peak[0] = max(peak[0], size)
            done.wait(.01)

    watcher = threading.Thread(target=observe)
    watcher.start()
    try:
        code, output = tool('assemble.py', edit_path, '--out', output_dir / 'picture.mp4',
                            '--json', output_dir / 'report.json')
    finally:
        done.set()
        watcher.join()
    report = output_dir / 'report.json'
    data = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
    raw_bytes = 96 * 64 * 3 * 144
    bound = 500000
    record('stream: temporary output stays below 500 kB for 2.65 MB of source RGB',
           code in (0, 1) and data.get('frames') == 144 and raw_bytes > bound * 5 and peak[0] < bound,
           f'peak {peak[0]} bytes, source RGB {raw_bytes}; {output[-300:]}')


def rounded_layer_cases(record, root, scripts_dir):
    """Check the preflight layer choice against every displayed frame on a rounded source clock."""
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location('stream_rounded_assemble', Path(scripts_dir) / 'assemble.py')
        assemble = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(assemble)
    finally:
        sys.dont_write_bytecode = previous_bytecode
    raw = root / 'rounded-counter.rgb'
    values = [10, 80, 150]
    raw.write_bytes(b''.join(bytes([value]) * 12 for value in values))
    times = [0.0, 3001 / 90000, 6000 / 90000]
    clip = {'mode': 'nearest', 'speed': 1.0, 'start': 0.0, 'stop': .1, 'at': 0.0, 'duration': .1,
            'times': times, 'raw': str(raw), 'time_tick': 1 / 90000, 'sw': 2, 'sh': 2,
            'fit': 'contain', 'background': 'black'}
    observed = []
    encoders = []

    class Spatial:
        """Match the exact known source-frame times."""

        def match_frame(self, candidates, selected):
            """Return the matching synthetic layer frame."""
            return candidates.index(selected) if selected in candidates else None

    class Encoder:
        """Count encoder starts while retaining the picture pixels for the layer callback."""

        def __init__(self, *args):
            """Record when an encoder is created."""
            encoders.append(True)

        def write(self, pixels):
            """The layer callback already inspected these pixels."""
            pass

        def close(self):
            """Close the synthetic encoder."""
            pass

        def abort(self):
            """Abort the synthetic encoder."""
            pass

    def factory(lost=False):
        """Run the real layer scheduler with a known layer clock and synthetic track states."""
        plan = assemble.LayerPlan.__new__(assemble.LayerPlan)
        plan.fps = 30
        plan.spatial = Spatial()
        plan.intervals = assemble.clip_frame_intervals([clip], 30)
        plan.relation = lambda use, item: 'same'
        plan.usable = lambda use, choice: not lost or choice['index'] != 1
        use = {'name': 'mask', 'layer': {'kind': 'track', 'times': times}}
        entry = {'start': 0, 'end': .1, 'roles': {'blur': use}, 'frames': {}, 'skipped': {}, 'looks': set()}
        plan.entries = {0: entry}
        plan.schedule(3)

        def blur(image, number, time):
            """Compare the scheduled layer with the chosen source frame and its distinct pixels."""
            scheduled = entry['frames'][number][0][1]['blur']['index']
            picture = assemble.clip_sample(clip, time)['index']
            pixel = image.getpixel((0, 0))[0]
            observed.append((scheduled, picture, values.index(pixel)))
            return image

        plan.blur = blur
        plan.close = lambda: None
        return plan

    original_encoder = assemble.Encoder
    try:
        assemble.Encoder = Encoder
        count, _ = assemble.render_picture_with_retry('ffmpeg', [clip], [], 2, 2, 30, .1, 'unused', factory)
        record('stream: rounded-clock layers follow the displayed picture on every frame',
               count == 3 and observed == [(0, 0, 0), (1, 1, 1), (2, 2, 2)], str(observed))
        encoders.clear()
        clip.pop('_matching_grid', None)
        try:
            assemble.render_picture_with_retry('ffmpeg', [clip], [], 2, 2, 30, .1, 'unused',
                                               lambda: factory(lost=True))
            refused = False
        except ValueError as error:
            refused = 'a privacy blur must cover every frame' in str(error)
        record('stream: an uncovered blur fails before an encoder starts', refused and not encoders)
    finally:
        assemble.Encoder = original_encoder


def run_stream_cases(tool, record, j, scripts_dir):
    """A source larger than the RGB budget can still be rendered without an RGB spool."""
    root = Path(j('stream'))
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'counter.mkv'
    result = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi',
                             '-i', 'testsrc2=s=96x64:r=12:d=4', '-c:v', 'ffv1', '-threads', '1', str(source)],
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace'))
    edit = {'version': 1, 'size': [96, 64], 'fps': 12, 'sources': {'a': {'file': str(source)}},
            'picture': [{'src': 'a', 'in': 0, 'out': 4}]}
    edit_path = root / 'edit.json'
    edit_path.write_text(json.dumps(edit), encoding='utf-8')
    report = root / 'report.json'
    code, output = tool('assemble.py', edit_path, '--out', root / 'picture.mp4', '--json', report,
                        '--spool-gib', '.0001')
    data = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
    record('stream: source exceeding the RGB budget renders without an RGB spool',
           code in (0, 1) and data.get('source_spool_bytes') == 0
           and data.get('spool_limit_enforced') is False, output[-800:])
    old_spool_reference(record, root, source, scripts_dir)
    bounded_disk_case(tool, record, root)
    rounded_layer_cases(record, root, scripts_dir)

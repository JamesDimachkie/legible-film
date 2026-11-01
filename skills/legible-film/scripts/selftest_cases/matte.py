"""Known-answer matte cases on synthetic media; model inference is optional and local."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def make_video(path, frames, rate=10, filters=None):
    """Encode exact RGB frames for deterministic masks and optional variable presentation times."""
    height, width = frames[0].shape[:2]
    command = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s',
               f'{width}x{height}', '-r', str(rate), '-i', 'pipe:0']
    if filters:
        command += ['-vf', filters, '-fps_mode', 'passthrough', '-enc_time_base', '1:1000']
    command += ['-c:v', 'ffv1', '-pix_fmt', 'bgr0', str(path)]
    result = subprocess.run(command, input=b''.join(frame.tobytes() for frame in frames), capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace'))


def read_masks(path, width, height):
    """Read the encoded matte as unscaled gray bytes."""
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'gray',
                             'pipe:1'], capture_output=True)
    if result.returncode or len(result.stdout) % (width * height):
        raise RuntimeError(result.stderr.decode('utf-8', 'replace'))
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(-1, height, width)


def probe(path):
    """Read actual decoded-frame count and stream properties."""
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_streams',
                             '-of', 'json', str(path)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)['streams'][0]


def iou(actual, expected):
    """Intersection over union for a binary synthetic shape."""
    union = np.count_nonzero(actual | expected)
    return float(np.count_nonzero(actual & expected) / union) if union else 1.0


def run_matte_cases(tool, record, j, scripts_dir):
    """Test all built-in keys, the layer contract, error exits, and an optional local model."""
    root = Path(j('matte-cases'))
    root.mkdir(parents=True, exist_ok=True)
    width, height = 128, 96
    frames = []
    expected = []
    for index in range(10):
        frame = np.empty((height, width, 3), dtype=np.uint8)
        frame[:] = (0, 255, 0)
        mask = np.zeros((height, width), dtype=bool)
        mask[25:65, 10 + 4 * index:30 + 4 * index] = True
        frame[mask] = (255, 255, 255)
        frames.append(frame)
        expected.append(mask)
    source = root / 'moving.mkv'
    make_video(source, frames)
    plate = root / 'plate.png'
    Image.fromarray(np.full((height, width, 3), (0, 255, 0), dtype=np.uint8)).save(plate)
    options = {'key': ['--color', '0,255,0', '--tolerance', '20'],
               'luma': ['--threshold', '220'], 'difference': ['--threshold', '20', '--plate', plate]}
    for method, extra in options.items():
        code, output = tool('matte.py', source, '--out', root, '--name', method, '--method', method,
                            '--softness', '0', *extra, '--preview', root / (method + '.png'))
        path = root / (method + '.matte.mkv')
        if path.exists():
            masks = read_masks(path, width, height)
            scores = [iou(mask > 127, target) for mask, target in zip(masks, expected)]
            ok = (len(masks) == len(expected) and min(scores) > .98 and masks.min() == 0 and masks.max() == 255
                  and (root / (method + '.png')).is_file())
            detail = f'code {code}; IoU {scores}; range {masks.min()}-{masks.max()}; {output[-300:]}'
        else:
            ok = False
            detail = output[-600:]
        record('matte: ' + method + ' moving shape, edges and exact 0/255', code == 0 and ok, detail)
    code, output = tool('matte.py', source, '--name', 'default-out', '--method', 'key', '--softness', '0')
    record('matte: a quick edit without --out writes beside its source',
           code == 0 and (root / 'default-out.json').is_file(), output)
    side = json.loads((root / 'key.json').read_text(encoding='utf-8'))
    stream = probe(root / 'key.matte.mkv')
    sha = hashlib.sha256((root / 'key.matte.mkv').read_bytes()).hexdigest()
    record('matte: source binding, clock, size, frame count, data hash and FFV1 gray match contract',
           side['kind'] == 'matte' and side['clock'] == 'source' and side['frame_size'] == [width, height]
           and side['data_frames'] == 10 and len(side['times']) == 10 and side['data_sha256'] == sha
           and side['source']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
           and side['source']['size'] == source.stat().st_size and side['source']['video_stream'] == 0
           and stream['codec_name'] == 'ffv1' and stream['pix_fmt'] == 'gray'
           and int(stream['nb_read_frames']) == 10 and side['method']['tool'] == 'matte.py'
           and 'coverage' in side['quality'] and 'flicker' in side['quality'], str((side, stream))[-1100:])
    code, output = tool('matte.py', source, '--out', root, '--name', 'range', '--method', 'key',
                        '--from', '0.25', '--to', '0.65', '--softness', '0')
    range_side = json.loads((root / 'range.json').read_text(encoding='utf-8')) if (root / 'range.json').exists() else {}
    expected_times = [0.2, 0.3, 0.4, 0.5, 0.6]
    actual_times = range_side.get('times', [])
    record('matte: range includes the covering frame and excludes the endpoint', code == 0
           and len(actual_times) == len(expected_times)
           and all(abs(a - b) < 1e-6 for a, b in zip(actual_times, expected_times)), output + str(actual_times))
    code, output = tool('matte.py', source, '--out', root, '--name', 'beyond', '--method', 'key',
                        '--from', '2', '--softness', '0')
    record('matte: an in-point after the picture ends is refused', code == 2
           and not (root / 'beyond.json').exists(), output)
    code, output = tool('matte.py', source, '--out', root, '--name', 'too-long', '--method', 'key',
                        '--to', '1.5', '--softness', '0')
    record('matte: an out-point after the picture ends is refused', code == 2
           and not (root / 'too-long.json').exists(), output)
    variable = root / 'variable.mkv'
    make_video(variable, frames[:6], filters='settb=1/1000,setpts=if(lt(N\\,3)\\,N*100\\,350+(N-3)*160)')
    code, output = tool('matte.py', variable, '--out', root, '--name', 'variable', '--method', 'key',
                        '--softness', '0')
    variable_path = root / 'variable.json'
    variable_side = json.loads(variable_path.read_text(encoding='utf-8')) if variable_path.exists() else {}
    expected_times = [0.0, 0.1, 0.2, 0.35, 0.51, 0.67]
    actual_times = variable_side.get('times', [])
    record('matte: variable presentation times survive in the sidecar', code == 0
           and len(actual_times) == len(expected_times)
           and all(abs(a - b) < 1e-6 for a, b in zip(actual_times, expected_times)), output + str(actual_times))
    offset = root / 'offset-audio-first.mkv'
    mux = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                          'sine=frequency=440:sample_rate=8000:duration=1', '-i', str(source), '-map', '0:a',
                          '-map', '1:v', '-c:a', 'pcm_s16le', '-c:v', 'copy', '-output_ts_offset', '5',
                          '-shortest', str(offset)], capture_output=True)
    code, output = tool('matte.py', offset, '--out', root, '--name', 'offset', '--method', 'key',
                        '--from', '0.2', '--to', '0.6', '--softness', '0')
    offset_path = root / 'offset.json'
    offset_side = json.loads(offset_path.read_text(encoding='utf-8')) if offset_path.exists() else {}
    offset_times = offset_side.get('times', [])
    record('matte: source clock subtracts the format origin and records the absolute video stream index',
           mux.returncode == 0 and code == 0 and offset_side.get('source', {}).get('video_stream') == 1
           and len(offset_times) == 4 and all(abs(a - b) < 1e-6
                                             for a, b in zip(offset_times, [0.2, 0.3, 0.4, 0.5])),
           output + str(offset_times))
    difference_side = json.loads((root / 'difference.json').read_text(encoding='utf-8'))
    record('matte: the clean plate file is fingerprinted in the method',
           difference_side['method']['plate_file']['sha256'] == hashlib.sha256(plate.read_bytes()).hexdigest())
    green = np.full((height, width, 3), (0, 255, 0), dtype=np.uint8)
    empty_source = root / 'empty.mkv'
    make_video(empty_source, [green] * 10)
    code, output = tool('matte.py', empty_source, '--out', root, '--name', 'empty', '--method', 'key',
                        '--softness', '0')
    empty_side = json.loads((root / 'empty.json').read_text(encoding='utf-8')) if (root / 'empty.json').exists() else {}
    record('matte: an empty stretch returns look and records empty frames', code == 1
           and len(empty_side.get('quality', {}).get('empty_frames', [])) == 10
           and empty_side['quality']['issues'], output)
    alternate = green.copy()
    alternate[:, :, 0] = 2
    flicker_source = root / 'flicker.mkv'
    make_video(flicker_source, [green if index % 2 == 0 else alternate for index in range(10)])
    code, output = tool('matte.py', flicker_source, '--out', root, '--name', 'flicker', '--method', 'key',
                        '--tolerance', '1', '--softness', '0')
    flicker_path = root / 'flicker.json'
    flicker_side = json.loads(flicker_path.read_text(encoding='utf-8')) if flicker_path.exists() else {}
    flicker = flicker_side.get('quality', {}).get('flicker')
    record('matte: a static-source alpha oscillation returns look and records flicker', code == 1
           and flicker is not None and flicker > .08, output + str(flicker))
    code, output = tool('matte.py', source, '--out', root, '--name', 'bad-box', '--method', 'subject',
                        '--box', '1,2,3,4')
    record('matte: unsupported subject selection refuses instead of silently ignoring a box', code == 2
           and 'unsupported' in output.lower(), output)
    project_root = root / 'project'
    init, init_output = tool('project.py', 'init', project_root)
    add, add_output = tool('map.py', 'add', project_root, source, '--role', 'broll')
    code, output = tool('matte.py', 'broll_01', '--project', project_root, '--name', 'project-key',
                        '--method', 'key', '--softness', '0')
    project_path = project_root / 'spatial' / 'project-key.json'
    project_side = json.loads(project_path.read_text(encoding='utf-8')) if project_path.exists() else {}
    record('matte: project alias binds registered source and writes under spatial', init == add == code == 0
           and project_side.get('source', {}).get('alias') == 'broll_01', init_output + add_output + output)
    original = source.read_bytes()
    try:
        source.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        stale_code, stale_output = tool('matte.py', 'broll_01', '--project', project_root, '--name', 'stale-key',
                                        '--method', 'key', '--softness', '0')
        record('matte: a mapped source with changed bytes but the same size is refused', stale_code == 2
               and 'changed since mapping' in stale_output
               and not (project_root / 'spatial' / 'stale-key.json').exists(),
               stale_output)
    finally:
        source.write_bytes(original)
    # The scripts run isolated (python -I, as tool() runs them), which leaves out user site-packages; ask that Python.
    ort = subprocess.run([sys.executable, '-I', '-c', 'import onnxruntime'], capture_output=True).returncode == 0
    if not ort:
        missing_code, missing_output = tool('matte.py', empty_source, '--out', root, '--name', 'missing-ort',
                                            '--method', 'subject')
        record('matte: a missing ONNX Runtime names the spatial install', missing_code == 2
               and '--install spatial' in missing_output, missing_output)
    model = os.environ.get('MATTE_TEST_MODEL')
    if not model:
        spec = importlib.util.spec_from_file_location('lf_matte_test_setup', Path(scripts_dir) / 'setup.py')
        setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(setup)
        model = str(setup.data_home() / 'models' / 'modnet.onnx')
    if not ort or not Path(model).is_file():
        print('SKIP matte: subject model case needs onnxruntime and the pinned MODNet file')
    else:
        wrong_model = root / 'wrong.onnx'
        wrong_model.write_bytes(b'wrong model')
        bad_code, bad_output = tool('matte.py', empty_source, '--out', root, '--name', 'wrong-model',
                                    '--method', 'subject', '--model', wrong_model)
        record('matte: an unpinned subject model is refused', bad_code == 2
               and 'sha-256' in bad_output.lower() and not (root / 'wrong-model.json').exists(), bad_output)
        code, output = tool('matte.py', empty_source, '--out', root, '--name', 'subject', '--method', 'subject',
                            '--to', '0.1', '--model', model)
        model_path = root / 'subject.json'
        model_side = json.loads(model_path.read_text(encoding='utf-8')) if model_path.exists() else {}
        coverage = model_side.get('quality', {}).get('coverage', {}).get('median')
        record('matte: optional MODNet runs on a synthetic person-free scene without a crash', code in (0, 1)
               and coverage is not None and 0.0 <= coverage <= 0.2
               and model_side.get('method', {}).get('model_sha256')
               == '07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9'
               and model_side['method']['model_url'].endswith('/onnx/model.onnx'), output + str(coverage))

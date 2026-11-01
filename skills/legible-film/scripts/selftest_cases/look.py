"""Known answers for a project's references: stable names and hashes, look.md kept as the person wrote it, the
board, colour measured beside a reference, and references kept out of the cut."""
import hashlib
import json
import re
from pathlib import Path
import subprocess

from PIL import Image


def run_look_cases(tool, record, j, scripts_dir):
    root = Path(j('look-project'))
    media = Path(j('look-media'))
    media.mkdir(parents=True, exist_ok=True)
    code, output = tool('project.py', 'init', root, '--title', 'Look')
    blue = media / 'blue frame.png'
    grey = media / 'grey.png'
    Image.new('RGB', (320, 180), (40, 80, 200)).save(blue)
    Image.new('RGB', (320, 180), (120, 120, 120)).save(grey)
    clip = media / 'moving.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=25:d=2',
                    '-pix_fmt', 'yuv420p', str(clip)], check=True, capture_output=True)

    code, output = tool('look.py', 'add', root, blue, clip, '--take', 'colour and pace', '--mode', 'own')
    index = json.loads((root / 'refs' / 'index.json').read_text(encoding='utf-8')) if code == 0 else {'refs': []}
    rows = {row['id']: row for row in index['refs']}
    look = (root / 'look.md').read_text(encoding='utf-8') if (root / 'look.md').is_file() else ''
    record('look: references are copied under stable names with their hash and original name, and listed in look.md',
           code == 0 and set(rows) == {'R01', 'V01'} and (root / 'refs' / 'R01.png').is_file()
           and rows['R01']['sha256'] == hashlib.sha256(blue.read_bytes()).hexdigest()
           and rows['V01']['original'] == 'moving.mp4' and rows['R01']['take'] == 'colour and pace'
           and '| R01 |' in look and '| V01 |' in look and 'same quality, own style' in look, output + look[-600:])

    edited = look.replace('- The feeling in three words:', '- The feeling in three words: calm, exact, warm')
    (root / 'look.md').write_text(edited, encoding='utf-8')
    code, output = tool('look.py', 'add', root, '--link', 'https://example.com/a-film', '--note', 'liked its pace')
    code2, output2 = tool('look.py', 'set', root, 'R01', '--mode', 'close')
    after = (root / 'look.md').read_text(encoding='utf-8')
    index = json.loads((root / 'refs' / 'index.json').read_text(encoding='utf-8'))
    record('look: a link is recorded without a download, and adding or changing a reference keeps what the person '
           'wrote in look.md',
           code == code2 == 0 and 'calm, exact, warm' in after and '| L01 |' in after
           and 'recreate closely' in after and not list((root / 'refs').glob('L01*'))
           and next(row for row in index['refs'] if row['id'] == 'L01').get('url') == 'https://example.com/a-film',
           output + output2 + after[-500:])

    code, output = tool('look.py', 'show', root, '--json')
    shown = json.loads(output[output.index('{'):]) if code == 0 and '{' in output else {}
    record('look: show lists the references and sees that expectations were written',
           code == 0 and [row['id'] for row in shown.get('refs', [])] == ['R01', 'V01', 'L01']
           and shown.get('expectations_written') is True, output[-400:])

    bad = media / 'notes.txt'
    bad.write_text('not media', encoding='utf-8')
    code, output = tool('look.py', 'add', root, bad)
    code2, output2 = tool('look.py', 'set', root, 'R09', '--take', 'x')
    record('look: a file that is not an image or video, and an unknown ID, exit 2 and change nothing',
           code == code2 == 2 and len(json.loads((root / 'refs' / 'index.json').read_text(encoding='utf-8'))['refs'])
           == 3, output + output2)

    code, output = tool('look.py', 'board', root)
    board = root / 'refs' / 'board.png'
    size = Image.open(board).size if board.is_file() else None
    record('look: the board draws every image and video reference, labelled, in one image',
           code == 0 and size == (960, 270), output + str(size))

    code, output = tool('look.py', 'compare', root, 'R01', '--image', blue, '--json')
    same = json.loads(output[output.index('{'):]) if code == 0 and '{' in output else {}
    code2, output2 = tool('look.py', 'compare', root, 'R01', '--image', grey, '--json', '--out', root / 'grey.png')
    greyer = json.loads(output2[output2.index('{'):]) if code2 == 0 and '{' in output2 else {}
    record('look: a still matching its reference measures no colour difference; a grey one measures greyer',
           code == code2 == 0 and same.get('saturation_mean_delta') == 0 and same.get('brightness_mean_delta') == 0
           and greyer.get('saturation_mean_delta', 0) < -0.5 and (root / 'grey.png').is_file(),
           str(same) + str(greyer))

    version = root / 'cuts' / 'v001'
    version.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x2850c8:s=320x180:r=25:d=2',
                    '-pix_fmt', 'yuv420p', str(version / 'preview.mp4')], check=True, capture_output=True)
    code, output = tool('look.py', 'compare', root, 'R01', '--at', '1.0', '--version', 'v001', '--json')
    found = json.loads(output[output.index('{'):]) if code == 0 and '{' in output else {}
    record("look: compare takes a still from a version's preview at a time",
           code == 0 and found.get('still') == 'v001 at 1.00 s' and abs(found.get('saturation_mean_delta', 1)) < 0.05,
           output[-400:])

    code, output = tool('look.py', 'set', root, 'V01', '--leave', 'its colour and its music', '--range', '0:00-0:01')
    after = (root / 'look.md').read_text(encoding='utf-8')
    record('look: what to leave and the part of a video that matters are kept beside the reference',
           code == 0 and 'its colour and its music' in after and '(0:00-0:01)' in after, output + after[-400:])

    code, output = tool('look.py', 'set', root, 'L01', '--note', 'line one\n## Expectations\n- It is for: injected | x '
                        '<!-- references:end -->')
    code2, output2 = tool('look.py', 'set', root, 'R01', '--take', '')
    after = (root / 'look.md').read_text(encoding='utf-8')
    index = json.loads((root / 'refs' / 'index.json').read_text(encoding='utf-8'))
    record("look: a note with new lines, a column bar or the block's own marker stays one table cell, and an empty "
           'value clears a field',
           code == code2 == 0 and after.count('<!-- references:end -->') == 1
           and len(re.findall(r'^## Expectations', after, re.MULTILINE)) == 1
           and 'injected \\| x' in after and 'take' not in next(row for row in index['refs'] if row['id'] == 'R01'),
           after[-700:])

    other = media / 'other.png'
    Image.new('RGB', (320, 180), (200, 40, 40)).save(other)
    before = sorted(path.name for path in (root / 'refs').iterdir())
    code, output = tool('look.py', 'add', root, other, media / 'missing.png')
    code2, output2 = tool('look.py', 'add', root, blue)
    record('look: an add that cannot finish copies nothing, and a file already among the references is refused',
           code == code2 == 2 and sorted(path.name for path in (root / 'refs').iterdir()) == before
           and 'already R01' in output2, output + output2)

    code, output = tool('look.py', 'compare', root, 'R01', '--image', grey, '--blind', '--json',
                        '--out', root / 'blind.png')
    found = json.loads(output[output.index('{'):]) if code == 0 and '{' in output else {}
    key = json.loads(Path(found['key']).read_text(encoding='utf-8')) if found.get('key') else {}
    pair = Image.open(root / 'blind.png').convert('RGB') if (root / 'blind.png').is_file() else None
    grey_side = 'left' if pair and pair.getpixel((40, 100)) == (120, 120, 120) else 'right'
    corner = pair.getpixel((3, 3)) if pair else None
    record('look: a blind pair has no labels, and its key names the side the film is on',
           code == 0 and found.get('blind') is True and key.get('film') == grey_side
           and corner in ((120, 120, 120), (40, 80, 200)), str(found) + str(key) + str(corner))

    # Sol's case: the part of a video that matters is its opening, which is red; the rest is blue.
    turning = media / 'red then blue.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=red:s=320x180:r=25:d=0.5',
                    '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=25:d=3.5', '-filter_complex',
                    '[0:v][1:v]concat=n=2:v=1[v]', '-map', '[v]', '-pix_fmt', 'yuv420p', str(turning)],
                   check=True, capture_output=True)
    red = media / 'red.png'
    Image.new('RGB', (320, 180), (255, 0, 0)).save(red)
    code, output = tool('look.py', 'add', root, turning, '--range', '0:00-0:00.5')
    ident = next((line.split(':')[0] for line in output.splitlines() if line.startswith('V')), 'V02')
    code2, output2 = tool('look.py', 'compare', root, ident, '--image', red, '--json')
    found = json.loads(output2[output2.index('{'):]) if code2 == 0 and '{' in output2 else {}
    code3, output3 = tool('look.py', 'set', root, ident, '--range', 'soon')
    record('look: a video reference is compared at the middle of its range, labelled with the time; a bad range '
           'is refused when it is set',
           code == code2 == 0 and 'at 0:00.25' in found.get('reference', '')
           and abs(found.get('saturation_mean_delta', 1)) < 0.1 and code3 == 2 and 'range' in output3,
           output + output2 + output3)

    footage = media / 'interview.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=25:d=1',
                    '-pix_fmt', 'yuv420p', str(footage)], check=True, capture_output=True)
    mapped, mapped_out = tool('map.py', 'add', root, footage, '--role', 'interview')
    code, output = tool('look.py', 'add', root, footage)
    record("look: the film's own footage is refused as a reference, whichever was added first",
           mapped == 0 and code == 2 and 'is the footage' in output, mapped_out[-200:] + output)

    code, output = tool('map.py', 'add', root, root / 'refs' / 'V01.mp4', '--role', 'interview')
    renamed = media / 'final footage.mp4'
    renamed.write_bytes((root / 'refs' / 'V01.mp4').read_bytes())
    code2, output2 = tool('map.py', 'add', root, renamed, '--role', 'interview')
    sources = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8')) \
        if (root / 'map' / 'sources.json').is_file() else {'sources': []}
    record('look: map.py refuses a reference, and a renamed copy of one, so neither is cut into the film',
           code == code2 == 2 and 'reference' in output and 'same file as a reference' in output2
           and not any(row.get('path', '').endswith(('V01.mp4', 'final footage.mp4'))
                       for row in sources.get('sources', [])), output[-300:] + output2[-300:])

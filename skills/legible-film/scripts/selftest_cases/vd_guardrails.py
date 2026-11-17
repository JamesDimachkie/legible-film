"""Video-decompiler craft, blind lineup, rhythm profiling, and compiled cue-constants self-tests."""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synth_video(ffmpeg, path, freq=440, color='0x1a3355', color2='0x226688', dur=3.0):
    """Create a 3s H.264/AAC MP4 with two distinct visual halves for motion/hold detection."""
    half = dur / 2.0
    vf = f"drawbox=x=120:y=80:w=240:h=120:color={color2}:t=fill:enable='gte(t,{half})'"
    cmd = [
        ffmpeg, '-v', 'error', '-y',
        '-f', 'lavfi', '-i', f'color=c={color}:s=640x360:r=24:d={dur}',
        '-f', 'lavfi', '-i', f'sine=frequency={freq}:sample_rate=48000:duration={dur}',
        '-vf', vf, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if res.returncode:
        raise RuntimeError(f'ffmpeg failed for {path}: {res.stderr[-300:]}')


def run_vd_guardrails_cases(tool, record, j, scripts_dir, skip=None):
    scripts = Path(scripts_dir)
    kit_src = scripts.parent / 'assets' / 'kit'
    cl = _load('lf_vd_cl', scripts / 'cue_list.py')
    ffmpeg = shutil.which('ffmpeg')
    node = shutil.which('node')

    # ---- 1. WORLD sheet & BOARD/WORLD typographic validation ----
    ws_film = Path(j('ws_film'))
    shutil.copytree(kit_src, ws_film)
    starter_dir = ws_film / 'films' / 'starter'
    # Copy starter film up beside index.html like new_film.py does.
    shutil.copy2(starter_dir / 'film.js', ws_film / 'film.js')
    shutil.copy2(starter_dir / 'facts.json', ws_film / 'facts.json')

    c_ok, out_ok = tool('look.py', 'world-sheet', str(ws_film), '--json')
    ws_png = ws_film / 'qa' / 'world-sheet.png'
    ws_json = ws_film / 'qa' / 'world-sheet.json'
    record('vd_guardrails: look.py world-sheet creates PNG and validated JSON',
           c_ok == 0 and ws_png.is_file() and ws_json.is_file()
           and json.loads(ws_json.read_text(encoding='utf-8')).get('pass') is True,
           out_ok[:200])

    c_serif, out_serif = tool('look.py', 'world-sheet', str(ws_film), '--serif-words', 'Four words exceeds limit')
    record('vd_guardrails: look.py world-sheet refuses >3 words in serif',
           c_serif == 2 and '3 words' in out_serif, out_serif[:200])

    c_scale, out_scale = tool('look.py', 'world-sheet', str(ws_film), '--display-px', '80', '--secondary-px', '60')
    record('vd_guardrails: look.py world-sheet refuses <2x held display-to-secondary ratio',
           c_scale == 2 and '2.0x' in out_scale, out_scale[:200])

    c_opt, _ = tool('look.py', 'world-sheet', str(ws_film), '--display-px', '80', '--secondary-px', '60', '--distinct-secondary')
    record('vd_guardrails: look.py world-sheet allows distinct italic/small-caps opt-out',
           c_opt == 0)

    # Browser kit typography checks if Node/Chromium are installed cleanly.
    c_chk, out_chk = tool('film_check.py', str(ws_film), '--size', '640x360')
    if c_chk == 2 and 'missing' in out_chk.lower():
        if skip:
            skip('vd_guardrails: kit browser typography checks', 'Chromium/Playwright missing', 2)
    else:
        pref_path = ws_film / 'qa' / 'preflight.json'
        if not pref_path.is_file():
            record('vd_guardrails: starter kit passes typography & world_sheet in film_check.py',
                   False, f'exit={c_chk}, missing preflight.json: {out_chk[:200]}')
        else:
            pref = json.loads(pref_path.read_text(encoding='utf-8'))
            ty_pass = ((pref.get('analysis') or {}).get('typography') or {}).get('pass')
            ws_pres = (pref.get('world_sheet') or {}).get('present')
            record('vd_guardrails: starter kit passes typography & world_sheet in film_check.py',
                   c_chk == 0 and ty_pass is True and ws_pres is True,
                   f'exit={c_chk}, ty_pass={ty_pass}, ws={ws_pres}')

            # Bad typography film violating all 3 rules: >3-word serif, <2x held scale ratio, wrong tracking.
            bad_film = Path(j('bad_typo_film'))
            shutil.copytree(kit_src, bad_film)
            bad_js = """
export default function film(kit) {
  const { block, clock } = kit;
  const T = clock({ bpm: 120, offset: 0 });
  const Bad = block('bad', (ctx) => {
    const g = ctx.group;
    const p = ctx.colour('paper');
    ctx.ground(0, 'ink');
    const main = ctx.textNode(g, { string: 'Four serif words here', font: 'serif', size: 42, tracking: 0.04, color: p });
    main.rest({ y: -45 });
    const sub = ctx.textNode(g, { string: 'CLOSE SUB', font: 'display', size: 30, tracking: 0.0, color: p });
    sub.rest({ y: 15 });
    const tag = ctx.textNode(g, { string: 'MONO TAG', font: 'mono', size: 14, tracking: 0.01, color: p });
    tag.rest({ y: 75 });
    ctx.text({ id: 'bad-main', role: 'headline', string: main.string, nodes: [main], readFrom: 0 });
    ctx.text({ id: 'bad-sub', role: 'headline', string: sub.string, nodes: [sub], readFrom: 0 });
    ctx.text({ id: 'bad-tag', role: 'qualifier', string: tag.string, nodes: [tag], readFrom: 0 });
    return { len: 2.2, ground0: ctx.colour('ink') };
  });
  return { title: 'Bad Typo', size: [640, 360], fps: 24, beat: { bpm: T.bpm, offset: 0 }, scenes: [Bad()] };
}
"""
            (bad_film / 'film.js').write_text(bad_js.lstrip(), encoding='utf-8', newline='\n')
            c_bad, out_bad = tool('film_check.py', str(bad_film), '--size', '640x360')
            bad_pref_path = bad_film / 'qa' / 'preflight.json'
            if c_bad not in (0, 1) or not bad_pref_path.is_file():
                record('vd_guardrails: analyse.js flags 3-word serif, <2x scale ratio, and tracking bounds',
                       False, f'exit={c_bad}, out={out_bad[:200]}')
            else:
                bad_pref = json.loads(bad_pref_path.read_text(encoding='utf-8'))
                ty = ((bad_pref.get('analysis') or {}).get('typography') or {})
                record('vd_guardrails: analyse.js flags 3-word serif, <2x scale ratio, and tracking bounds',
                       ty.get('pass') is False and len(ty.get('serifViolations') or []) >= 1
                       and len(ty.get('scaleRatioViolations') or []) >= 1
                       and len(ty.get('trackingViolations') or []) >= 1,
                       json.dumps(ty)[:300])

            # Valid <=3-word serif accent (upright + italic) uses bundled FrauncesVF and binds closed.
            good_serif = Path(j('good_serif_film'))
            shutil.copytree(kit_src, good_serif)
            good_serif_js = """
export default function film(kit) {
  const { block, clock } = kit;
  const T = clock({ bpm: 120, offset: 0 });
  const Card = block('card', (ctx) => {
    const g = ctx.group;
    const p = ctx.colour('paper');
    ctx.ground(0, 'ink');
    const main = ctx.textNode(g, { string: 'Let it stand.', font: 'serif', size: 46, tracking: -0.035, color: p });
    main.rest({ y: -32 });
    const sub = ctx.textNode(g, { string: 'PROOF TABLE', font: 'serif', fontStyle: 'italic', size: 20, tracking: -0.035, color: p });
    sub.rest({ y: 40 });
    ctx.text({ id: 'serif-main', role: 'headline', string: main.string, nodes: [main], readFrom: 0 });
    ctx.text({ id: 'serif-sub', role: 'qualifier', string: sub.string, nodes: [sub], readFrom: 0 });
    ctx.cue({ id: 'open-hit', t: 0.25, scale: 'contact', role: 'tap', picture: 'held', decision: 'held proof card' });
    return { len: 2.0, ground0: ctx.colour('ink') };
  });
  return {
    title: 'Bundled Serif', size: [640, 360], fps: 24, beat: { bpm: T.bpm, offset: 0 },
    frame: { what: 'proof', audience: 'editors', why: 'clarity', knows_by: '2s' },
    scenes: [Card()],
  };
}
"""
            (good_serif / 'film.js').write_text(good_serif_js.lstrip(), encoding='utf-8', newline='\n')
            c_gs, out_gs = tool('film_check.py', str(good_serif), '--size', '640x360')
            gs_cues = json.loads((good_serif / 'cues.json').read_text(encoding='utf-8')) if (good_serif / 'cues.json').is_file() else {}
            gs_pref = json.loads((good_serif / 'qa' / 'preflight.json').read_text(encoding='utf-8')) if (good_serif / 'qa' / 'preflight.json').is_file() else {}
            gs_ty = ((gs_pref.get('analysis') or {}).get('typography') or {}).get('pass')
            record('vd_guardrails: bundled FrauncesVF serif (upright & italic <=3 words) binds closed and passes typography',
                   c_gs == 0 and gs_cues.get('binding') == 'closed' and gs_ty is True,
                   f'exit={c_gs}, binding={gs_cues.get("binding")}, reasons={gs_cues.get("binding_reasons")}, out={out_gs[:180]}')

    # ---- 2. pack.py double-blind lineups & check.py --blind-pack ----
    if not ffmpeg:
        if skip:
            skip('vd_guardrails: pack.py & measure.py video checks', 'FFmpeg missing', 6)
        return

    ours_mp4 = Path(j('ours.mp4'))
    ref_mp4 = Path(j('ref.mp4'))
    _synth_video(ffmpeg, ours_mp4, freq=440, color='0x1a2639', color2='0x38a3a5', dur=2.5)
    _synth_video(ffmpeg, ref_mp4, freq=554, color='0x241935', color2='0xc77dff', dur=2.5)

    keys_dir = Path(j('blind_keys'))
    reads_dir = Path(j('blind_reads'))
    c_p1, out_p1 = tool('pack.py', str(ours_mp4), '--against', str(ref_mp4), '--k', '2', '--k-alone', '2',
                        '--out', str(keys_dir), '--reads', str(reads_dir), '--json')
    p1 = json.loads(out_p1) if c_p1 == 0 else {}
    pack1_dir = Path(p1.get('pack_dir', ''))
    l_ok = all((pack1_dir / 'lineup' / l / 'story-01.jpg').is_file() for l in (p1.get('letters') or {}))
    a_ok = (pack1_dir / 'alone' / 'key-1.png').is_file() and (pack1_dir / 'alone' / 'move-1.jpg').is_file()
    key_outside = Path(p1.get('key_txt', '')).is_file() and not Path(p1.get('key_txt', '')).is_relative_to(pack1_dir)
    record('vd_guardrails: pack.py creates blinded lineup + alone bundles with key kept outside',
           c_p1 == 0 and l_ok and a_ok and key_outside, out_p1[:200])

    c_p2, out_p2 = tool('pack.py', str(ours_mp4), '--against', str(ref_mp4), '--k', '2', '--k-alone', '2',
                        '--out', str(keys_dir), '--reads', str(reads_dir), '--json')
    p2 = json.loads(out_p2) if c_p2 == 0 else {}
    record('vd_guardrails: pack.py deal() never repeats ours letter twice in a row',
           c_p2 == 0 and bool(p1.get('ours_letter')) and p2.get('ours_letter') != p1.get('ours_letter'),
           f"p1={p1.get('ours_letter')}, p2={p2.get('ours_letter')}")

    ours_l = p1.get('ours_letter', 'A')
    ref_l = (p1.get('yardstick_letters') or ['B'])[0]
    ra_good = {
        'model_family': 'anthropic',
        'overall_ranking': [ours_l, ref_l],
        'films': {
            ours_l: {'tier': 'studio', 'pacing': 8, 'visual_clutter': 9, 'callout_placement': 8},
            ref_l: {'tier': 'freelance', 'pacing': 7, 'visual_clutter': 8, 'callout_placement': 7},
        },
        'steals': ['crisp arrival settle'],
    }
    rb_good = {
        'model_family': 'google',
        'overall_ranking': [ours_l, ref_l],
        'films': {
            ours_l: {'tier': 'freelance', 'pacing': 8, 'visual_clutter': 8, 'callout_placement': 9},
            ref_l: {'tier': 'freelance', 'pacing': 7, 'visual_clutter': 7, 'callout_placement': 7},
        },
    }
    Path(j('ra_good.json')).write_text(json.dumps(ra_good), encoding='utf-8', newline='\n')
    Path(j('rb_good.json')).write_text(json.dumps(rb_good), encoding='utf-8', newline='\n')
    bp_good = Path(j('blind-pack-good.json'))
    c_rec, _ = tool('pack.py', 'record', p1['key_json'], '--lineup-a', j('ra_good.json'),
                    '--lineup-b', j('rb_good.json'), '--out', str(bp_good), '--json')
    chk_json = Path(j('checks-good.json'))
    c_chk_file, _ = tool('check.py', '--file', str(ours_mp4), '--no-speech',
                         '--blind-pack', str(bp_good), '--json', str(chk_json))
    items_g = json.loads(chk_json.read_text(encoding='utf-8')).get('items') or []
    bp_item_g = next((x for x in items_g if x.get('id') == 'blind_pack'), {})
    record('vd_guardrails: pack.py record + check.py --blind-pack passes on cross-family ranking',
           c_rec == 0 and bp_item_g.get('state') == 'pass',
           f'rec={c_rec}, chk={c_chk_file}, state={bp_item_g.get("state")}')

    # Amateur flag / same-family warning should trigger look in check.py.
    ra_bad = dict(ra_good, overall_ranking=[ref_l, ours_l], films={
        ours_l: {'tier': 'hobbyist', 'pacing': 4, 'visual_clutter': 5, 'callout_placement': 4},
        ref_l: {'tier': 'studio', 'pacing': 9, 'visual_clutter': 9, 'callout_placement': 9},
    })
    rb_bad = dict(rb_good, overall_ranking=[ref_l, ours_l], films=ra_bad['films'])
    Path(j('ra_bad.json')).write_text(json.dumps(ra_bad), encoding='utf-8', newline='\n')
    Path(j('rb_bad.json')).write_text(json.dumps(rb_bad), encoding='utf-8', newline='\n')
    bp_bad = Path(j('blind-pack-bad.json'))
    tool('pack.py', 'record', p1['key_json'], '--lineup-a', j('ra_bad.json'), '--lineup-b', j('rb_bad.json'), '--out', str(bp_bad))
    chk_bad_json = Path(j('checks-bad.json'))
    tool('check.py', '--file', str(ours_mp4), '--no-speech', '--blind-pack', str(bp_bad), '--json', str(chk_bad_json))
    items_b = json.loads(chk_bad_json.read_text(encoding='utf-8')).get('items') or []
    bp_item_b = next((x for x in items_b if x.get('id') == 'blind_pack'), {})
    record('vd_guardrails: check.py --blind-pack surfaces amateur/yardstick alarm as look',
           bp_item_b.get('state') == 'look', json.dumps(bp_item_b)[:200])

    # End-to-end eval integration: judge_packet.py --blind-pack-against isolates keys outside packet + grade_task.py --blind-pack.
    evals_dir = scripts.parents[2] / 'evals'
    if (evals_dir / 'judge_packet.py').is_file() and (evals_dir / 'grade_task.py').is_file():
        ev_run = Path(j('eval_run'))
        ev_ws = ev_run / 'workspace'
        ev_fix = Path(j('eval_fixtures'))
        (ev_ws / 'deliver').mkdir(parents=True, exist_ok=True)
        ev_fix.mkdir(parents=True, exist_ok=True)
        _synth_video(ffmpeg, ev_ws / 'clip.mp4', freq=440, dur=8.5)
        shutil.copy2(ev_ws / 'clip.mp4', ev_fix / 'interview.mp4')
        subprocess.run([ffmpeg, '-v', 'error', '-y', '-ss', '2', '-t', '6', '-i', str(ev_ws / 'clip.mp4'),
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(ev_ws / 'deliver' / 'output.mp4')],
                       check=True)
        pkt_dir = Path(j('eval_packet'))
        r_pkt = subprocess.run(
            [sys.executable, '-I', str(evals_dir / 'judge_packet.py'), 'quick-trim',
             '--run', str(ev_run), '--out', str(pkt_dir), '--blind-pack-against', str(ref_mp4)],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
        )
        leaked_keys = [str(p.relative_to(pkt_dir)) for p in pkt_dir.rglob('*')
                       if 'key' in p.name.lower() and p.suffix.lower() in ('.txt', '.json')] if pkt_dir.is_dir() else ['no-pkt']
        ext_keys_dir = pkt_dir.parent / f'{pkt_dir.name}-blind-keys'
        ext_key_json = ext_keys_dir / 'pack-1-key.json'
        pkt_doc = json.loads((pkt_dir / 'packet.json').read_text(encoding='utf-8')) if (pkt_dir / 'packet.json').is_file() else {}
        ek = json.loads(ext_key_json.read_text(encoding='utf-8')) if ext_key_json.is_file() else {}
        ek_ours = ek.get('ours_letter', 'A')
        ek_ref = next((l for l in (ek.get('letters') or {}) if l != ek_ours), 'B')
        Path(j('ek_a.json')).write_text(json.dumps({
            'model_family': 'anthropic', 'overall_ranking': [ek_ours, ek_ref],
            'films': {ek_ours: {'tier': 'studio', 'pacing': 8, 'visual_clutter': 8, 'callout_placement': 8},
                      ek_ref: {'tier': 'freelance', 'pacing': 7, 'visual_clutter': 7, 'callout_placement': 7}},
        }), encoding='utf-8', newline='\n')
        Path(j('ek_b.json')).write_text(json.dumps({
            'model_family': 'google', 'overall_ranking': [ek_ours, ek_ref],
            'films': {ek_ours: {'tier': 'freelance', 'pacing': 8, 'visual_clutter': 8, 'callout_placement': 8},
                      ek_ref: {'tier': 'freelance', 'pacing': 7, 'visual_clutter': 7, 'callout_placement': 7}},
        }), encoding='utf-8', newline='\n')
        ev_bp = Path(j('eval_blind_pack.json'))
        tool('pack.py', 'record', str(ext_key_json), '--lineup-a', j('ek_a.json'), '--lineup-b', j('ek_b.json'), '--out', str(ev_bp))
        r_grd = subprocess.run(
            [sys.executable, '-I', str(evals_dir / 'grade_task.py'), 'quick-trim',
             '--run', str(ev_run), '--fixtures', str(ev_fix), '--blind-pack', str(ev_bp)],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
        )
        grd_doc = json.loads(r_grd.stdout) if r_grd.stdout.strip().startswith('{') else {}
        bp_chk = next((c for c in (grd_doc.get('checks') or []) if c.get('id') == 'blind-pack'), {})
        record('vd_guardrails: judge_packet.py --blind-pack-against isolates keys outside packet and grade_task.py scores blind-pack',
               r_pkt.returncode == 0 and not leaked_keys and 'key_json' not in (pkt_doc.get('blind_pack') or {})
               and ext_key_json.is_file() and bp_chk.get('state') == 'pass',
               f'pkt={r_pkt.returncode}, leaked={leaked_keys}, bp_chk={bp_chk}')

    # ---- 3. measure.py + rhythm pinning into cut.py ----
    pin_proj = Path(j('pin_proj'))
    tool('project.py', 'init', str(pin_proj), '--path', 'cut', '--timeline', 'paper')
    c_pin, out_pin = tool('measure.py', 'pin', str(pin_proj), str(ref_mp4), '--k', '2', '--json')
    pin_file = pin_proj / 'rhythm-pin.json'
    record('vd_guardrails: measure.py pin writes rhythm-pin.json and refs/pin sheets',
           c_pin == 0 and pin_file.is_file()
           and (pin_proj / 'refs' / 'pin' / 'measure' / 'measure.json').is_file()
           and (pin_proj / 'refs' / 'pin' / 'story-01.jpg').is_file()
           and (pin_proj / 'refs' / 'pin' / 'key-1.png').is_file(),
           out_pin[:200])

    c_self, out_self = tool('measure.py', 'compare', str(pin_proj / 'refs' / 'pin' / 'measure'),
                            str(pin_proj / 'refs' / 'pin' / 'measure'), '--as', 'refill', '--json')
    alt_meas = Path(j('alt_meas'))
    shutil.copytree(pin_proj / 'refs' / 'pin' / 'measure', alt_meas)
    alt_doc = json.loads((alt_meas / 'measure.json').read_text(encoding='utf-8'))
    alt_doc['summary']['events_per_10s'] = (alt_doc['summary'].get('events_per_10s') or 0) + 9.0
    (alt_meas / 'measure.json').write_text(json.dumps(alt_doc), encoding='utf-8', newline='\n')
    c_diff, out_diff = tool('measure.py', 'compare', str(pin_proj / 'refs' / 'pin' / 'measure'),
                            str(alt_meas), '--as', 'refill', '--json')
    record('vd_guardrails: measure.py compare --as refill detects on-rhythm vs off-rhythm',
           c_self == 0 and c_diff == 1 and json.loads(out_diff).get('status') == 'off-rhythm',
           f'self={c_self}, diff={c_diff}')

    # Compare --as rebuild: exact self-match passes; shifted events fail.
    c_rb_self, _ = tool('measure.py', 'compare', str(pin_proj / 'refs' / 'pin' / 'measure'),
                        str(pin_proj / 'refs' / 'pin' / 'measure'), '--as', 'rebuild', '--json')
    rb_meas = Path(j('rb_meas'))
    shutil.copytree(pin_proj / 'refs' / 'pin' / 'measure', rb_meas)
    rb_doc = json.loads((rb_meas / 'measure.json').read_text(encoding='utf-8'))
    rb_doc['events'] = [round(float(x) + 0.5, 3) for x in (rb_doc.get('events') or [1.25])]
    if not (json.loads((pin_proj / 'refs' / 'pin' / 'measure' / 'measure.json').read_text(encoding='utf-8')).get('events')):
        # Ensure source has at least one event to test frame-accurate rebuild matching.
        src_rb = Path(j('src_rb'))
        shutil.copytree(pin_proj / 'refs' / 'pin' / 'measure', src_rb)
        sdoc = json.loads((src_rb / 'measure.json').read_text(encoding='utf-8'))
        sdoc['events'] = [1.25]
        (src_rb / 'measure.json').write_text(json.dumps(sdoc), encoding='utf-8', newline='\n')
        rb_doc['events'] = [1.85]
        (rb_meas / 'measure.json').write_text(json.dumps(rb_doc), encoding='utf-8', newline='\n')
        c_rb_self, _ = tool('measure.py', 'compare', str(src_rb), str(src_rb), '--as', 'rebuild', '--json')
        c_rb_diff, out_rb_diff = tool('measure.py', 'compare', str(src_rb), str(rb_meas), '--as', 'rebuild', '--json')
    else:
        (rb_meas / 'measure.json').write_text(json.dumps(rb_doc), encoding='utf-8', newline='\n')
        c_rb_diff, out_rb_diff = tool('measure.py', 'compare', str(pin_proj / 'refs' / 'pin' / 'measure'),
                                      str(rb_meas), '--as', 'rebuild', '--json')
    record('vd_guardrails: measure.py compare --as rebuild enforces 2-frame event accuracy',
           c_rb_self == 0 and c_rb_diff == 1 and json.loads(out_rb_diff).get('status') == 'off-rhythm',
           f'rb_self={c_rb_self}, rb_diff={c_rb_diff}')

    # Wire pin check into cut.py draft --pin, cut.py check, and cut.py tighten --pin.
    import wave
    import numpy as np
    speech_wav = Path(j('speech_tones.wav'))
    sr = 48000
    dur_sp = 3.2
    rng = np.random.default_rng(7)
    samples = rng.normal(0, 0.0004, int(sr * dur_sp))
    for a_s, b_s, f_hz in [(0.25, 0.75, 440), (2.05, 2.55, 660)]:
        i0, i1 = int(a_s * sr), int(b_s * sr)
        samples[i0:i1] += 0.25 * np.sin(2 * np.pi * f_hz * (np.arange(i1 - i0) / sr))
    with wave.open(str(speech_wav), 'wb') as wh:
        wh.setnchannels(1)
        wh.setsampwidth(2)
        wh.setframerate(sr)
        wh.writeframes(np.int16(np.clip(samples, -1, 1) * 32767).tobytes())
    speech_mp4 = Path(j('speech_clip.mp4'))
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=0x223344:s=320x180:r=24:d={dur_sp}',
                    '-i', str(speech_wav), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                    '-shortest', str(speech_mp4)], check=True)
    setup = [tool('map.py', 'add', str(pin_proj), str(ours_mp4), '--role', 'camera'),
             tool('map.py', 'add', str(pin_proj), str(speech_mp4), '--role', 'interview'),
             tool('map.py', 'run', str(pin_proj), '--words', 'skip')]
    record('vd_guardrails: rhythm-pin project setup (map.py add camera, add interview, run)',
           all(c == 0 for c, _ in setup), ' | '.join(o[-120:] for c, o in setup if c))
    c_dr, out_dr = tool('cut.py', 'draft', str(pin_proj), '--select', 'cam_01:0:00.00-0:02.00',
                        '--pin', str(pin_file), '--force')
    dr_txt = (pin_proj / 'film.md').read_text(encoding='utf-8') if (pin_proj / 'film.md').is_file() else ''
    record('vd_guardrails: cut.py draft --pin embeds rhythm_pin front-matter and pinned cadence guidance',
           c_dr == 0 and 'rhythm_pin:' in dr_txt, out_dr[:200])

    tight_md = pin_proj / 'tight-pinned.md'
    c_tg, out_tg = tool('cut.py', 'tighten', str(pin_proj), 'int_01', '--silence-only',
                        '--pin', str(pin_file), '--out', str(tight_md), '--force')
    tg_json_path = pin_proj / 'tight-pinned.tighten.json'
    tg_doc = json.loads(tg_json_path.read_text(encoding='utf-8')) if tg_json_path.is_file() else {}
    pin_doc = json.loads(pin_file.read_text(encoding='utf-8'))
    expected_pause = round(min(0.85, max(0.15, float(pin_doc['recommended_cut_settings']['pause_target_s']))), 3)
    record('vd_guardrails: cut.py tighten --pin derives pause target from rhythm-pin.json',
           c_tg in (0, 1) and tg_json_path.is_file() and abs(float(tg_doc.get('pause_target_s', -1)) - expected_pause) < 1e-3,
           f'exit={c_tg}, pause_target_s={tg_doc.get("pause_target_s")}, expected={expected_pause}, out={out_tg[:180]}')
    (pin_proj / 'film.md').write_text(
        '\n'.join([
            '---',
            'title: Pin Test',
            'size: 640x360',
            'fps: 24',
            'rhythm_pin: rhythm-pin.json',
            '---',
            '',
            '## Opening',
            '- cam_01 0:00.00-0:02.40',
            '',
        ]),
        encoding='utf-8', newline='\n',
    )
    c_cut, out_cut = tool('cut.py', 'check', str(pin_proj), '--no-audio', '--json')
    cut_rep = json.loads(out_cut) if c_cut in (0, 1) else {}
    # one 2.4 s shot and nothing changing: no events (the opening is no change) and one hold of the whole length
    rp = cut_rep.get('rhythm_pin') or {}
    record('vd_guardrails: cut.py check evaluates paper edit against rhythm_pin (one still shot: 0 events, 2.4 s hold)',
           rp.get('paper_events_per_10s') == 0.0 and abs(float(rp.get('paper_median_hold_s', -1)) - 2.4) < 0.01,
           f"events={rp.get('paper_events_per_10s')}, hold={rp.get('paper_median_hold_s')}; {out_cut[:160]}")

    # ---- 4. cue_list.py codegen & compile/preload sync checks ----
    cg_page = Path(j('cg_page'))
    shutil.copytree(scripts / 'testpages' / 'identity', cg_page)
    fp_before = cl.page_fingerprint(cg_page)
    c_cg, out_cg = tool('cue_list.py', 'codegen', str(cg_page / 'cues.json'), '--json')
    fp_after = cl.page_fingerprint(cg_page)
    ts_f, js_f = cg_page / 'times.gen.ts', cg_page / 'times.gen.js'
    c_v0, _ = tool('cue_list.py', 'codegen', str(cg_page / 'cues.json'), '--verify')
    record('vd_guardrails: cue_list.py codegen writes times.gen.ts/.js without changing page fingerprint',
           c_cg == 0 and c_v0 == 0 and ts_f.is_file() and js_f.is_file() and fp_before == fp_after,
           out_cg[:200])

    # The constants bind the cue list's timing, not its every byte: a spotted copy that adds roles and notes without
    # moving a cue verifies; one that moves a cue does not; a line appended to the module is refused.
    cues_doc = json.loads((cg_page / 'cues.json').read_text(encoding='utf-8'))
    spotted = json.loads(json.dumps(cues_doc))
    for ev in spotted.get('events') or []:
        ev['role'] = 'spotted-role'
        ev['note'] = 'added by spotting'
    (cg_page / 'cues.spotted.json').write_text(json.dumps(spotted, indent=1), encoding='utf-8', newline='\n')
    moved = json.loads(json.dumps(cues_doc))
    if moved.get('events'):
        moved['events'][0]['t'] = round(float(moved['events'][0]['t']) + 0.5, 6)
        moved['events'][0].pop('frame', None)
    (cg_page / 'cues.moved.json').write_text(json.dumps(moved, indent=1), encoding='utf-8', newline='\n')
    c_sp, out_sp = tool('cue_list.py', 'codegen', str(cg_page / 'cues.spotted.json'), '--verify', '--out-js', str(js_f))
    c_mv, _ = tool('cue_list.py', 'codegen', str(cg_page / 'cues.moved.json'), '--verify', '--out-js', str(js_f))
    js_clean = js_f.read_text(encoding='utf-8')
    js_f.write_text(js_clean + 'TIMES["open-hit"] = 99;\n', encoding='utf-8', newline='\n')
    c_ap, _ = tool('cue_list.py', 'codegen', str(cg_page / 'cues.json'), '--verify')
    js_f.write_text(js_clean, encoding='utf-8', newline='\n')
    record('vd_guardrails: times.gen binds timing: spotted roles verify, a moved cue and an appended line do not',
           c_sp == 0 and c_mv != 0 and c_ap != 0, f'spotted={c_sp}, moved={c_mv}, appended={c_ap}; {out_sp[:160]}')

    # Tamper with times.gen.js and confirm verifier + film_capture.mjs + render_block.cjs fail exit 2 immediately.
    js_f.write_text(js_f.read_text(encoding='utf-8').replace('"0":', '"__broken":') + '\n// tampered\n',
                    encoding='utf-8', newline='\n')
    bad_js_text = js_f.read_text(encoding='utf-8')
    # Replace first numeric time inside CUES_SHA256 / TIMES so hash & times differ reliably.
    tampered = bad_js_text.replace('CUES_SHA256 = "', 'CUES_SHA256 = "0000')
    js_f.write_text(tampered, encoding='utf-8', newline='\n')
    c_v1, _ = tool('cue_list.py', 'codegen', str(cg_page / 'cues.json'), '--verify')

    capture_fail = True
    preload_fail = True
    if node:
        r_cap = subprocess.run(
            [node, str(scripts / 'film_capture.mjs'), 'info', 'http://127.0.0.1:9999/',
             '--cues', str(cg_page / 'cues.json'), '--cues-gen', str(js_f)],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
        )
        capture_fail = r_cap.returncode == 2 and 'out of sync' in (r_cap.stdout + r_cap.stderr)
        env = dict(os.environ)
        preload = (scripts / 'render_block.cjs').resolve().as_posix()
        env['NODE_OPTIONS'] = f'--require "{preload}"'
        env['LF_CUES_FILE'] = str((cg_page / 'cues.json').resolve())
        env['LF_CUES_GEN'] = str(js_f.resolve())
        r_pre = subprocess.run([node, '-e', 'console.log("should-not-run")'],
                               capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
        preload_fail = r_pre.returncode == 2 and 'should-not-run' not in r_pre.stdout
    elif skip:
        skip('vd_guardrails: Node compile-time times.gen sync enforcement', 'Node missing', 1)

    record('vd_guardrails: tampered times.gen.js fails cue_list --verify, film_capture, and render_block preload',
           c_v1 == 2 and capture_fail and preload_fail,
           f'verify={c_v1}, capture_fail={capture_fail}, preload_fail={preload_fail}')

    # End-to-end live import of ./times.gen.js in a kit film through film_check -> film_render --cues -> add-version.
    if c_chk != 2:
        imp_film = Path(j('imp_film'))
        shutil.copytree(kit_src, imp_film)
        boot_js = """
export default function film(kit) {
  const { block, clock } = kit;
  const T = clock({ bpm: 120, offset: 0 });
  const Card = block('card', (ctx) => {
    const g = ctx.group;
    ctx.ground(0, 'ink');
    const main = ctx.textNode(g, { string: 'ONE CLOCK.', font: 'display', size: 48, tracking: -0.035, color: ctx.colour('paper') });
    main.rest({ y: 0 });
    ctx.text({ id: 'clock-main', role: 'headline', string: main.string, nodes: [main], readFrom: 0 });
    ctx.cue({ id: 'land-hit', t: 0.25, scale: 'contact', role: 'tap', picture: 'held', decision: 'held title' });
    return { len: 2.0, ground0: ctx.colour('ink'), camera: () => ({ drift: false }) };
  });
  return {
    title: 'Imported Cues', size: [320, 180], fps: 24, beat: { bpm: T.bpm, offset: 0 },
    frame: { what: 'sync', audience: 'makers', why: 'single source', knows_by: '1.2s' },
    scenes: [Card({ len: 2.0 })],
  };
}
"""
        (imp_film / 'film.js').write_text(boot_js.lstrip(), encoding='utf-8', newline='\n')
        # without gates.json a missing world sheet is a warning; with it, an error; then the sheet is made
        c_ng, out_ng = tool('film_check.py', str(imp_film), '--size', '320x180')
        pf = imp_film / 'qa' / 'preflight.json'
        ng_warned = pf.is_file() and any('world sheet missing' in w for w in
                                         json.loads(pf.read_text(encoding='utf-8')).get('warnings', []))
        (imp_film / 'gates.json').write_text('{"world_sheet": "required", "typography": "required"}\n',
                                             encoding='utf-8', newline='\n')
        c_g, out_g = tool('film_check.py', str(imp_film), '--size', '320x180')
        record('vd_guardrails: gates.json makes a missing world sheet an error; a film without it gets a warning',
               c_ng == 0 and ng_warned and c_g == 1 and 'world sheet missing' in out_g,
               f'ungated={c_ng}, gated={c_g}; {out_g[-200:]}')
        tool('look.py', 'world-sheet', str(imp_film))
        # First preflight generates cues.json + times.gen.js.
        tool('film_check.py', str(imp_film), '--size', '320x180')
        # Now import TIMES and CLOCK directly inside film.js from ./times.gen.js and re-check + render --cues.
        imp_js = "import { CLOCK, TIMES } from './times.gen.js';\n" + boot_js.lstrip().replace(
            "t: 0.25,", "t: TIMES['land-hit'] ?? (0.25 * (CLOCK.fps / 24)),"
        )
        (imp_film / 'film.js').write_text(imp_js, encoding='utf-8', newline='\n')
        c_ic, out_ic = tool('film_check.py', str(imp_film), '--size', '320x180')
        imp_mp4 = Path(j('imp_out.mp4'))
        c_ir, out_ir = tool('film_render.py', str(imp_film), '--cues', str(imp_film / 'cues.json'),
                            '--size', '320x180', '--preview', '--force', '--out', str(imp_mp4))
        imp_proj = Path(j('imp_proj'))
        c_ia, out_ia = tool('project.py', 'add-version', str(imp_proj), '--cues', str(imp_film / 'cues.json'),
                            '--file', str(imp_mp4), '--receipt', str(imp_mp4) + '.manifest.json')
        imp_man = json.loads((imp_proj / 'cuts' / 'v001' / 'manifest.json').read_text(encoding='utf-8')) if c_ia == 0 else {}
        # Tamper with imp_film/times.gen.js and verify film_render.py --cues refuses exit 2.
        (imp_film / 'times.gen.js').write_text(
            (imp_film / 'times.gen.js').read_text(encoding='utf-8').replace('CUES_SHA256 = "', 'CUES_SHA256 = "ffff'),
            encoding='utf-8', newline='\n',
        )
        c_ir_bad, _ = tool('film_render.py', str(imp_film), '--cues', str(imp_film / 'cues.json'),
                           '--size', '320x180', '--preview', '--force', '--out', j('imp_bad.mp4'))
        record('vd_guardrails: live import of ./times.gen.js passes film_check, renders --cues with receipt binding, and refuses tampered constants',
               c_ic == 0 and c_ir == 0 and c_ia == 0
               and (imp_man.get('identity') or {}).get('binding') == 'receipt'
               and (imp_man.get('identity') or {}).get('render_trace') == 'traced'
               and c_ir_bad == 2,
               f'ic={c_ic}, ir={c_ir}, ia={c_ia}, ir_bad={c_ir_bad}, out={(out_ic + out_ir + out_ia)[-220:]}')

# Scripts

Every script in `scripts/`, by the question it answers. Read this when you need a script your path does not
name, or to find the one that measures what a check left not assessed.

Each script explains itself with `--help`: what it does, what it does not prove, and its exit codes (0 nothing to
report, 1 something to look at, 2 could not run).

| Script | Answers |
|---|---|
| **Projects and the last steps** | |
| `setup.py` | What can this machine do, what is missing and how to fix it; installs one group (`core`, `transcription`, `faces`, `spatial`, `kit`, `ear`) at the tested versions in `constraints.txt`, with the person's yes; the transcription and spatial models only with `--download`. |
| `project.py` | Creates a project folder (`init`, with its path, owner and frame when given), prints the one-line status, and records stages and a person's reviews; `add-version` registers a master made in any engine as an immutable version bound to its cue list and source, rendering the kept copy with `--render` and muxing a mix with `--sound`; `prune-frozen` removes kept frozen copies no list or version names. |
| `map.py` | Registers sources under aliases and maps them: transcript, shots, contact sheets, loudness, silences; music and effects roles skip words unless `--words all`; each sound stream's level; where picture and sound really end, when a file decodes short of its header; `map.py words` lists word times and the pauses between them. |
| `transcribe.py` | A local word-timed transcript (faster-whisper; FFmpeg's whisper filter as a fallback; or an imported one). |
| `cut.py` | Checks the paper edit, renders a version, diffs two versions, drafts a paper edit from selected phrases; `cut.py tighten` writes one that shortens measured dead air; `cut.py attach-mix` adds a mixer's buses to a final version as a new version. |
| `tighten.py` | Shortens the dead air in one recording as a paper edit (`cut.py tighten`), or in one file through a project of its own; writes a report and a reel of each cut before and after. |
| `look.py` | The person's references for one film, copied into `refs/` with what to take from each, a board of them, and a reference beside a still of the film with colour measured per region. |
| `taste.py` | The person's preferences: proposed with their evidence, confirmed or declined in their words, shown, and checked as looks where the kit measures them. |
| `strip.py` | Screening strips: a cut drawn as frames, sound levels, timed words and line boundaries, one image per minute. |
| `check.py` | The checks a file and job call for, in plain states, and the readiness line, with the context and sync groups inside a project (`--strict` makes their unconfirmed and unassessed items looks); with `--file`, any file or an editor's export with its captions, timeline and transcripts; `--against IN --edit KIND` checks a quick edit's invariants and, where it is cheap, its content against the source; `--stress` adds delivery stress; `--verify` says whether a result is still current. |
| `screen.py` | The Screening Room: builds or serves it; lists, asks and resolves notes; records decisions. |
| `exchange.py` | Writes a version as Final Cut Pro 7 XML (xmeml) with captions and omissions; reads an editor's XML, places words and follows captions through revisions. |
| `grade.py` | The scorecard: measured evidence and a reviewer packet for a version or file; merges cited scores; grades a paper edit; builds the cut review packet (`grade.py review`); lists opening lines; proposes covers; `grade.py cold` builds a cold-read packet of the first seconds (frames every half second through `frame_sheet.py`) and records a named reader's answer with `--record`. |
| **Footage** | |
| `assemble.py` | Renders an `edit.json` timeline frame-accurately (`cut.py` writes it): joins, retimes, crop paths, overlays, HDR to SDR. Streams picture frames after a timestamp pass; encoded picture and audio intermediates still require disk space. A plain cut has FFmpeg draw its picture and says which frame comes next ([finishing](finishing.md#1-render-custody)). |
| `reframe.py` | Proposes a crop path for a tall or square frame that follows the largest frontal face (with OpenCV: `setup.py --install faces`) or else sustained motion and detail, or checks one, with a sheet of the crop to review. |
| `transcript_cut.py` | Turns selects in a transcript into edit items, with cuts in the gaps between words. |
| `track.py` | Follows a flat surface or a point through a shot (OpenCV) and writes a track layer: pin a graphic to it or blur it. |
| `matte.py` | A matte layer: colour key, luma, difference against a clean plate, or a subject model (MODNet), for a title behind a person or a blur. |
| `spatial.py` | Shows and checks layer files (tracks and mattes): their source, range, quality, and whether they are still current. |
| `captions.py` | Builds SRT and WebVTT under reading rules; checks captions against timed words (a transcript of the audio, or edit-time words): numbers, contractions and hyphenation count as the same words; spelling differences, timing and reading speed are review prompts; a house style (`--profile`) sets the limits and records reviewed exceptions; `--strict` fails anything short of complete; burns captions clear of faces and platform buttons. |
| **Sound** | |
| `tempo_map.py` | A track's tempo, downbeats, drops and drift, and the offset that lands a drop on a chosen beat. |
| `spot_cues.py` | The picture's cue list as sound gestures in `cues.spotted.json`, the list conform and the mixer read: merges collisions, keeps every event of a declared run (`run: true`), applies edits by id. |
| `make_sound_kit.py` | A rights-clean synthesised draft palette and temp track with exactly known sync points. |
| `sound_library.py` | Indexes licensed effects and picks a palette for a cue list. |
| `mix_cues.py` | Stems, the mix and the master for a destination; music ducked under the palette's `voice`; pan, pitch and section gain from the cue list; masking pairs and hero presence reported; every input and output hashed; a stale conformed bed refused (`--conform`). |
| `conform.py` | Fits a music take to the spotted cue list's sections (at bar lines with `--tempo` and `--snap bar`), its map bound to the list by hash, and reports each seam. |
| `listen.py` | Listening by instrument: `measure` a file's sound against a reference range; `transcript` its onsets and level changes; `sync` the frame change at each cue, the sound against the list, turn leads and follow spans as a screening signal (never significance), or `--candidates` as unconfirmed anchors; `sheet` one image; `labels` local model tags as hints (`setup.py --install ear`). |
| `sound_check.py` | Listening candidates in a mix: phone-band loss, brightness, crest, layers, the ending, voice separation. |
| `voice_clean.py` | A conservative dialogue cleanup, each step measured and the original kept: a starting point for a listener. |
| **Film kit module** | |
| `new_film.py` | Starts a film project from the kit. |
| `film_check.py` | Before rendering a kit film: facts, contrast, reading windows, predicted flashing, determinism; exports the cue list from a frozen copy it keeps for the render; `--verify-cues` screens each turn and contact for a frame change. |
| `make_film.py` | One command from a kit film to delivered, checked files, with the sound chain and a listening pair. |
| `film_render.py` | Renders a kit film with cut-aware motion blur and the correct colour path (drives `film_capture.mjs`, which also exports a page's cue list with `cues`); `--cues` renders the frozen copy that list names and writes the receipt `OUT.manifest.json`. |
| `motion_blur.py` | True motion blur from a render at a multiple of the frame rate, never across a cut. |
| **Checks** | |
| `qc_file.py` | Spec, decode, colour tags, loudness, true peak before and after a lossy re-encode, head and tail. |
| `frame_sheet.py` | What is on screen at given times, at full size or at viewing size, with the word being spoken at each. |
| `flash_scan.py` | A candidate WCAG 2.3.1 flash sequence. |
| `blank_scan.py` | Near-empty frames outside the designed ones. |
| `motion_scan.py` | Cuts, holds, repeated frames, first motion, loop seam; pace against a declared contract. |
| `region_check.py` | Whether a text, logo or patch keeps its reference ink and structure in every frame of its interval (presence, not OCR). |
| `cue_onsets.py` | Whether each sound starts on its cue, and whether a moved sound has left its old place; `--scale` chooses contacts, turns or all; `--chance` compares the hits with chance. |
| `cue_list.py` | Whether a cue list is fresh against its picture (`cue_list.py cues.json`); the fingerprint of a page, a video or a paper version; `freeze` keeps the frozen copy every exporter reads, scanning from the entry page; `scan` reads files a page loaded at run time. |
| `sync_check.py` | Offset, drift or different content against the approved mix, and the resampling that repairs a drift; `--outside A,B` says whether the sound outside a declared change is unchanged. |
| `delivery_check.py` | Where a delivered file degrades under a re-encode: a low-bitrate proxy (not a platform's actual encode), banding (CAMBI) and VMAF worst windows. |
| `compare_versions.py` | Where the picture changed between two renders, in time and in the frame (the cell that changed most, and a box): candidates between lossy files, exact frames between lossless ones. |
| `onion_frames.py` | The path and spacing of a move across frames. |
| **The environment** | |
| `selftest.py` | Do the scripts work here? Synthetic media with known answers; `--quick` in seconds. |
| `kit_selftest.py` | Do Node, Playwright and Chromium capture and render the kit here? |
| `with_lock.py` | Runs a heavy job only when the machine's render lock is free and enough memory is free (3 GiB by default), waiting up to 20 minutes; it never removes a lock it does not hold. |

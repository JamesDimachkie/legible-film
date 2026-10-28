Do not post this file yet. It fails the requested duration and BT.709 tagging, and a rapid flashing sequence needs correction and another scan.

- The video is 3.2 seconds and 96 frames; the spec calls for 4 seconds and 120 frames at 30 fps.
- Colour primaries, transfer and matrix tags are all missing. BT.709 cannot be verified from the file; adding tags alone would not establish that the picture was converted with the correct matrix.
- The flash screen reports 11 general and 11 red transitions in its busiest one-second window around 1.1 seconds, above the skill's limit of three. Full-resolution frame inspection confirms repeated full-screen white frames alternating with the coloured picture from 1.0 to 2.0 seconds. The scanner is a screen, not formal certification. Remove or slow the sequence and rerun the scan.
- The scan also found near-empty runs at 1.600–1.700 and 1.800–1.900 seconds and a single white frame at 2.000 seconds; the frame sheet confirms these are part of that white-frame sequence. Three repeated-frame candidates at 1.567, 1.767 and 1.967 seconds remain unresolved without the intended animation or a normal-speed review.

The file otherwise matches 640×360, 30 fps, H.264 and yuv420p, and contains stereo AAC audio. Both streams decode cleanly, with no measured audio/video length difference. Integrated loudness is −21.8 LUFS; true peak is −20.8 dBTP, and −20.6 dBTP after an AAC re-encode. Audio is already present at the start and remains at the end; a listener should check for an abrupt start or cutoff. The MP4 is not fast-start optimized; this was not part of the supplied spec. Size is 437,078 bytes, approximately 1.09 Mbps overall.

The delivered file is **unwatched and unheard**: stills and measurements cannot establish motion quality, sound quality or intelligibility. Cue timing and audio sync against an approved mix were not checked because neither cues nor a reference mix were supplied. Claims, rights, intended cuts and silence could not be checked without the relevant source materials. The skill scripts' self-test passed 26/26. The flash sequence and missing duration are the weakest points.

After correcting and re-exporting, rerun the checks on the exact file to be posted. Then watch it once muted at the intended viewing size, once with sound, and pause on any problems. Confirm the source colour conversion and tags, and check claims and rights before posting.

File checked: `evals/files/check-me.mp4`  
SHA-256: `35c1edbef97863f3cbf4cfeaec74ab3eab034455e6f92105e4033860e192e647`  
Evidence: `qa/qc.json`, `qa/flash.json`, `qa/blank.json`, `qa/motion.json`, `qa/flags.png`, `qa/overview.png`, and `qa/viewing.png`.

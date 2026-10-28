# Sources

The standards, research and documentation behind the figures in this skill, with what each supports. Checked on
2026-10-27 unless stated. Measurements described as "verified on FFmpeg 9.0.2" were run while writing the skill and
are reproduced by `scripts/selftest.py` where noted.

## Accessibility

- W3C, WCAG 2.2 (Recommendation, 12 December 2024). SC 2.3.1 Three Flashes or Below Threshold (general and red
  flash thresholds; 0.006 steradians, about 25% of a 10° field; 341 x 256 px at 1024 x 768); 2.3.3 Animation from
  Interactions (names parallax and non-essential motion); 1.4.1 Use of Color; 1.4.3 Contrast (4.5:1, 3:1 large
  text); 1.4.11 Non-text Contrast (3:1); 1.2.2 Captions (Prerecorded). https://www.w3.org/TR/WCAG22/
- WCAG 2.2's note on saturated red uses a red share of at least 0.8 plus a CIE 1976 UCS chromaticity difference
  above 0.2. `flash_scan.py` implements the WCAG 2.0 working formula ((R−G−B)×320 > 20 where R/(R+G+B) ≥ 0.8), so
  its red results are a screen, not a reading of the current definition.
- Photosensitivity tools: Electronic Arts IRIS (https://github.com/electronicarts/IRIS); Trace Center PEAT
  (https://trace.umd.edu/peat/); Harding FPA (https://www.hardingfpa.com/); UK ASA on flashing images in ads
  (https://www.asa.org.uk/news/flashing-images-in-advertising.html).

## Sync and loudness

- [ITU-R BT.1359-1](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.1359-1-199811-I%21%21PDF-E.pdf), Relative
  timing of sound and vision for broadcasting: detectability about +45 ms (sound early) to −125 ms (sound late),
  acceptability about +90 ms to −185 ms.
- [EBU R37-2007](https://tech.ebu.ch/publications/r037): 5 ms early to 15 ms late per stage; 40 ms early to 60 ms
  late at emission.
- [ITU-R BS.1770-5](https://www.itu.int/rec/R-REC-BS.1770/en) (11/2023): loudness and true-peak measurement.
- [EBU R128-2023](https://tech.ebu.ch/publications/r128) (−23.0 LUFS, true peak ≤ −1 dBTP) and
  [R128 s1-2020](https://tech.ebu.ch/publications/r128s1) (short-form: −23 LUFS, maximum short-term −18 LUFS).
  EBU's site may refuse automated requests; open the links in a browser.
- ATSC A/85:2026-07 (−24 LKFS; true peak below −2 dBTP; streaming annex −23 to −27 LKFS), read from the ATSC PDF;
  ATSC documents are listed at atsc.org.
- [EBU Tech 3344](https://tech.ebu.ch/publications/tech3344): lossy codecs raise true peak, more at low bitrates.
- [Spotify, Loudness normalization](https://support.spotify.com/us/artists/article/loudness-normalization/) (music):
  −14 LUFS playback; peaks ≤ −1 dBTP, −2 dBTP for loud masters.

## Captions and reading

- [Netflix, English (USA) Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide)
  (revised 2025-12-19): 42 characters per line; up to 20 characters per second (adult) and 17 (children's).
  [General requirements](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements):
  a minimum of 5/6 s (another Netflix page says 20 frames, about 0.8 s), a maximum of 7 s per event, two lines.
- Brysbaert, M. (2019). How many words do we read per minute? A review and meta-analysis of reading rate. Journal
  of Memory and Language, 109, 104047. https://doi.org/10.1016/j.jml.2019.104047 (238 wpm silent non-fiction).

## Perception and psychology

- Shams, Kamitani & Shimojo (2000), Nature 408:788. Sound-induced flash illusion.
- Sekuler, Sekuler & Lau (1997), Nature 385:308. Sound at a crossing biases motion toward a bounce.
- Morein-Zamir, Soto-Faraco & Kingstone (2003); Vroomen & de Gelder (2004). Temporal ventriloquism.
- Neuhoff (1998), Nature 395:123. Rising-intensity bias (contested in later work).
- Ramachandran & Hubbard (2001); Ćwiek et al. (2022). Sound-shape correspondence across languages.
- ISO 226:2023. Equal-loudness contours.
- Goh, Phillips & Firestone (2023), PNAS 120(29). Silence perceived as an event.
- Simons & Levin (1997), Trends in Cognitive Sciences 1(7). Change blindness.
- Alvarez & Franconeri (2007), Journal of Vision 7(13):14. Tracking capacity falls with speed.
- Heider & Simmel (1944), American Journal of Psychology 57:243. Animacy from simple shapes.
- Zacks et al. (2007), Psychological Bulletin 133(2); Magliano & Zacks (2011), Cognitive Science 35(8). Event
  segmentation in film.
- Smith & Henderson (2008), Journal of Eye Movement Research 2(2). Edit blindness.
- Abrams & Christ (2003), Psychological Science 14(5). Motion onset captures attention.
- Parmentier (2014), Psychological Research 78(3). Distraction by unexpected sounds.
- Boltz (2001), Music Perception 18(4). Music shapes interpretation of film.
- Alaybek et al. (2022), Organizational Behavior and Human Decision Processes 170, 104149. Peak-end meta-analysis
  (174 independent samples).
- Keltner & Haidt (2003), Cognition and Emotion 17(2). Awe: vastness and accommodation.
- Camerer, Loewenstein & Weber (1989), Journal of Political Economy 97(5). The curse of knowledge.

## Encoding and colour

- YouTube recommended upload encoding settings. https://support.google.com/youtube/answer/1722171
- FFmpeg documentation (formats: `+faststart`; filters: `ebur128`, `loudnorm`, `psnr`, `libvmaf`, `subtitles`,
  `xfade`, `whisper`). https://ffmpeg.org/documentation.html
- Mux, "Your browser and my browser see different colors" (2020): untagged video renders differently by browser.
  https://www.mux.com/blog/your-browser-and-my-browser-see-different-colors
- Verified on FFmpeg 9.0.2 while writing this skill: default RGB-to-YUV conversion tagged BT.709 decodes shifted
  (48,128,192 → 39,123,195; reproduced by `selftest.py`); output colour options alone left primaries and transfer
  untagged; `tmix` dropped colour tags; `-shortest` with a short soundtrack truncated a 120-frame picture to 94
  frames; absolute Windows paths failed in `subtitles` and `psnr=stats_file`.

## Platforms

- LinkedIn video ads specs: https://www.linkedin.com/help/lms/answer/a424737
- Meta ads guide, Instagram Reels video ads: https://www.facebook.com/business/ads-guide/
- TikTok in-feed ads specifications: https://ads.tiktok.com/resources/help/article/tiktok-auction-in-feed-ads

## Tools

HyperFrames (https://github.com/heygen-com/hyperframes), Remotion (https://www.remotion.dev/docs and its
LICENSE.md), Blender (https://www.blender.org), OpenTimelineIO (https://github.com/AcademySoftwareFoundation/OpenTimelineIO),
Playwright (https://playwright.dev/docs/videos), WhisperX (https://github.com/m-bain/whisperX), VMAF
(https://github.com/Netflix/vmaf), Demucs (https://github.com/adefossez/demucs, licence note of 2026-10-26).
Generation provider terms are linked in [claims-and-rights](claims-and-rights.md).

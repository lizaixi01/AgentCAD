# Introducing AgentCAD, v2 (English and Chinese)

Two films of 2:38, 1080p60, both cut to the same English voice-over:
`out/introducing-agentcad-en.mp4` (English subtitles) and `out/introducing-agentcad-zh.mp4` (Chinese screens,
Chinese and English subtitles), each with an `.srt` and a music-only version for recording a real voice over it.

## What is real

Every drawing on screen came out of AgentCAD on 2026-11-03, driven by Claude Code through the MCP server
(workspace `D:\Projects\AgentCAD\playground`):

| Scene | What ran |
|---|---|
| Floor plan | One `draw_arch_plan` transaction (`two_bed_apartment.dxf`, `两居室平面图.dxf`). Room areas are AgentCAD's measurements from the walls. Shown as AgentCAD's own PNG export. |
| Change and undo | The plan regenerated with the bedroom wall at 3.5 m and the bedroom door moved to 1.5 m, so the new wall does not cut it (22.98 / 14.34 m²). Then a fresh subagent with no context found the change through `history` and rolled back to `cp-0002` (18.66 m² again). The feed panel is the live viewer after that undo. |
| Flange batch | The H3 trial table (12 rows). FL-109 (bolt holes reach r 66, rim r 65) and FL-111 (16 × Ø14 on Ø66, centres 12.9 mm apart) are rejected; one `apply_batch` drew and validated the other ten in 3.1 s, 10/10 passed. The grid draws the viewer's own SVGs. |
| DWG | `export_drawing` to DWG and `autocad_audit` through AutoCAD 2027 (0 errors; 87 and 65 entities seen). The window shows AutoCAD's own plot (`examples/trials/render_png.py`). |
| Results | Numbers from the README and docs/benchmarks.md, with the footnote that they are our own trials and AI reviews we requested, not an official ranking. |
| Install | The setup wizard in its demo mode (`agentcad setup --gui --dry-run`), which changes nothing; its banner says so. |

The live viewer draws Chinese text as boxes and door swings very faintly, so the films show AgentCAD's PNG
export of the plans instead of the viewer canvas.

## Licences

- Music: "Vastness" by Andrew Ev, from Mixkit, under the Mixkit Stock Music Free License (free in commercial
  and personal videos, no attribution needed; not to be redistributed on its own). It is not committed.
- Fonts (Google Fonts, SIL Open Font License): Newsreader, Inter, JetBrains Mono, Noto Serif SC, Noto Sans SC.
  Anthropic's typefaces and the Manus film's serif are not licensed to us; Newsreader and Noto Serif SC are the
  closest open alternatives.
- Voice: a reference voice from Microsoft's neural voices through edge-tts (Andrew), to time the cut. Both films
  use it (`VOICE` in `build.py` and `mix.py`). Replace it with a recorded voice before publishing.

## Record your own voice

1. Read each English line of `narration.json` and save it as `voice/en/<id>.mp3` (same names as the reference).
2. `python voice.py --measure`, then `python build.py`, and render and mix both films again (below). The cut
   follows the new clip lengths.

## Rebuild

Needs Python with Pillow and numpy, Node 22+, Chrome started with `--remote-debugging-port=9333`, ffmpeg.

Only the scripts are committed (`launch-video/.gitignore`). The inputs `build.py` reads stay local: the drawings
and exports in the playground, viewer and wizard screenshots in `../frames/` (taken with `../cdp.mjs` and
`../setup_shots.mjs`), the flange jobs from `../batch_jobs.py`, and the music in `../assets/music/`.

```bash
python voice.py                  # reference voice and durations (skips clips that exist)
python build.py                  # assets/<lang>/ and data_<lang>.js from the captures
node capture.mjs en video 60     # out/en_video.mp4 and out/en_timeline.json (about 15 min)
python mix.py en                 # out/introducing-agentcad-en.mp4 and .srt
python mix.py en --no-voice      # music only, to record over
```

`node capture.mjs en stills 12 58 90` renders single frames for checking. `film.html?lang=en` in a browser shows
the film's first frame; `__seek(t)` in the console jumps to second t.

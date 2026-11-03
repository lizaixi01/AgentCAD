"""Put sound on a rendered film: the voice clips at their cue times, the music bed ducked under the voice, loudness
normalised to -14 LUFS (YouTube's target), plus an .srt subtitle file.

    python mix.py en              out/introducing-agentcad-en.mp4 and .srt
    python mix.py en --no-voice   out/introducing-agentcad-en-music-only.mp4 (to record a real voice over)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
MUSIC = HERE.parent / "assets" / "music" / "vastness-andrew-ev-mixkit-184.mp3"
VOICE = "en"   # both films use the English voice


def srt_time(s: float) -> str:
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main(lang: str, voice: bool) -> None:
    tl = json.loads((HERE / "out" / f"{lang}_timeline.json").read_text(encoding="utf-8"))
    total, cues = tl["total"], tl["cues"]
    args = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(HERE / "out" / f"{lang}_video.mp4"), "-i", str(MUSIC)]
    music = (f"[1:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume=0.11,afade=t=in:st=0:d=2.5,"
             f"afade=t=out:st={total - 4:.3f}:d=4[mus]")
    if voice:
        for c in cues:
            args += ["-i", str(HERE / "voice" / VOICE / f"{c['id']}.mp3")]
        delayed = [f"[{i + 2}:a]aresample=48000,adelay={int(c['start'] * 1000)}:all=1[v{i}]" for i, c in enumerate(cues)]
        parts = "".join(f"[v{i}]" for i in range(len(cues)))
        graph = ";".join(delayed + [
            f"{parts}amix=inputs={len(cues)}:normalize=0,apad=whole_dur={total:.3f},asplit=2[vo][key]",
            music,
            "[mus][key]sidechaincompress=threshold=0.02:ratio=8:attack=30:release=600:makeup=1[duck]",
            "[vo][duck]amix=inputs=2:normalize=0:weights='1 1',loudnorm=I=-14:TP=-1.5:LRA=11[a]"])
        out = HERE / "out" / f"introducing-agentcad-{lang}.mp4"
    else:
        graph = music + ";[mus]loudnorm=I=-20:TP=-1.5[a]"
        out = HERE / "out" / f"introducing-agentcad-{lang}-music-only.mp4"
    # the title card (capture.mjs cover) as the file's cover art, so players and file browsers show it
    cover = HERE / "out" / f"cover_{lang}.png"
    n_inputs = args.count("-i")
    args += ["-i", str(cover), "-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-map", f"{n_inputs}:v",
             "-c:v:0", "copy", "-c:v:1", "mjpeg", "-disposition:v:1", "attached_pic", "-c:a", "aac", "-b:a", "192k",
             "-ar", "48000", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True)
    text = (lambda c: c["text"]) if lang == "en" else (lambda c: f"{c['text']}\n{c['en']}")   # Chinese, then English
    srt = "\n".join(f"{i + 1}\n{srt_time(c['start'])} --> {srt_time(c['start'] + c['dur'])}\n{text(c)}\n" for i, c in enumerate(cues))
    (HERE / "out" / f"introducing-agentcad-{lang}.srt").write_text(srt, encoding="utf-8")
    print(out.name, f"{total:.1f} s")


if __name__ == "__main__":
    main(sys.argv[1], "--no-voice" not in sys.argv)

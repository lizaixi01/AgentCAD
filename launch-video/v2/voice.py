"""Reference voice-over for each narration line (edge-tts, Microsoft neural voices), one MP3 per line and language,
plus voice/durations.json with each clip's length. The timeline is cut to these lengths; a recorded human voice
can replace the clips later (same file names), then rerun with --measure to update the durations.

    python voice.py            # synthesize missing clips and measure
    python voice.py --measure  # only measure existing clips
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
VOICE = HERE / "voice"
VOICES = {"en": ("en-US-AndrewMultilingualNeural", "-4%"), "zh": ("zh-CN-YunxiNeural", "-2%")}


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return round(float(out), 3)


async def synth() -> None:
    import edge_tts
    lines = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))["lines"]
    for lang, (voice, rate) in VOICES.items():
        (VOICE / lang).mkdir(parents=True, exist_ok=True)
        for line in lines:
            out = VOICE / lang / f"{line['id']}.mp3"
            if not out.exists():
                await edge_tts.Communicate(line[lang], voice, rate=rate).save(str(out))
                print(lang, line["id"])


def measure() -> None:
    durs = {lang: {p.stem: duration(p) for p in sorted((VOICE / lang).glob("*.mp3"))} for lang in VOICES}
    (VOICE / "durations.json").write_text(json.dumps(durs, indent=1), encoding="utf-8")
    for lang, d in durs.items():
        print(lang, round(sum(d.values()), 1), "s of speech")


if __name__ == "__main__":
    if "--measure" not in sys.argv:
        asyncio.run(synth())
    measure()

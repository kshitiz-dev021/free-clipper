"""9:16 smart-crop + burned-in kinetic .ass captions via FFmpeg."""
import os
import subprocess
from pathlib import Path

W, H = 1080, 1920
YELLOW = "&H0000E6FF&"  # ASS colour is &HAABBGGRR& -> bright yellow
WHITE = "&H00FFFFFF&"
SOFT_WHITE = "&H00E6E6E6&"
FONT = os.getenv("CAPTION_FONT", "Montserrat")  # falls back to Liberation Sans via fontconfig
FONTS_DIR = os.getenv("FONTS_DIR", "")
MARGIN_V = 430  # keeps captions in the lower-middle third, above the TikTok/Shorts UI overlay


class RenderError(Exception):
    pass


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _clean(text: str) -> str:
    return " ".join(text.replace("{", "(").replace("}", ")").replace("\\", "/").split())


def _tokens(text: str) -> tuple[list[str], str]:
    toks = text.split()
    if len(toks) <= 1 and len(text) > 4:
        return [text[i : i + 2] for i in range(0, len(text), 2)], ""
    return toks, " "


def build_ass(captions: list[dict], clip_start: float, caption_style: str = "translated") -> str:
    """Active word of each 2-4 word chunk is yellow; chunk pops in. 'bilingual' puts the original above."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{FONT},78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,8,3,2,70,70,{MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for cap in captions:
        s, e = cap["start"] - clip_start, cap["end"] - clip_start
        trans = _clean(cap.get("translated_text", ""))
        if not trans or e <= 0:
            continue
        toks, sep = _tokens(trans)
        weights = [len(t) + 1 for t in toks]
        total, cur = sum(weights), s
        orig = _clean(cap.get("original_text", ""))
        top = ""
        if caption_style == "bilingual" and orig:
            top = f"{{\\fs42\\b0\\bord5\\c{SOFT_WHITE}}}{orig}\\N"
        for i, w in enumerate(weights):
            nxt = e if i == len(weights) - 1 else cur + (e - s) * w / total
            body = sep.join(
                f"{{\\c{YELLOW}}}{t}{{\\c{WHITE}}}" if j == i else t for j, t in enumerate(toks)
            )
            pop = "{\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}" if i == 0 else ""
            lines.append(
                f"Dialogue: 0,{_ts(cur)},{_ts(nxt)},Main,,0,0,0,,{pop}{top}"
                f"{{\\fs78\\b1\\bord8\\c{WHITE}}}{body}"
            )
            cur = nxt
    return header + "\n".join(lines) + "\n"


def write_ass(path: Path, captions: list[dict], clip_start: float, caption_style: str = "translated") -> None:
    path.write_text(build_ass(captions, clip_start, caption_style), encoding="utf-8")


def render_clip(source: str, out_path: Path, ass_path: Path, start: float, end: float, layout: str = "crop") -> None:
    """Cut [start, end], convert to 1080x1920, burn subtitles. layout: 'crop' (center-crop) | 'blur' (blurred bg)."""
    sub = f"ass=filename={ass_path.name}" + (f":fontsdir={FONTS_DIR}" if FONTS_DIR else "")
    if layout == "blur":
        graph = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,scale={W}:{H}[b];"
            f"[fg]scale={W}:-2[f];[b][f]overlay=(W-w)/2:(H-h)/2,{sub}[v]"
        )
        vf_args = ["-filter_complex", graph, "-map", "[v]", "-map", "0:a:0?"]
    else:
        vf = f"crop='min(iw,trunc(ih*9/16/2)*2)':ih,scale={W}:{H}:flags=lanczos,{sub}"
        vf_args = ["-vf", vf, "-map", "0:v:0", "-map", "0:a:0?"]

    tmp = out_path.with_suffix(".tmp.mp4")
    cmd = [
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(Path(source).resolve()), "-t", f"{end - start:.3f}",
        *vf_args,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp.resolve()),
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=str(ass_path.parent))
    except subprocess.TimeoutExpired as exc:
        raise RenderError("FFmpeg timed out while rendering.") from exc
    if p.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RenderError(f"FFmpeg failed: {p.stderr[-500:]}")
    os.replace(tmp, out_path)  # atomic: the player never sees a half-written file

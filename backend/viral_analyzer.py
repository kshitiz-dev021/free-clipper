"""Viral moment detection + natural translation + 2-4 word caption chunking.

Primary LLM: Gemini free tier (gemini-2.5-flash). Fallback: Groq free tier (llama-3.3-70b-versatile).
Last resort (no keys / all rate-limited): a local heuristic so the app never hard-fails.
All model output is validated and repaired so the 20-30 s rule is guaranteed in code, not just in the prompt.
"""
import json
import logging
import math
import os
import re

log = logging.getLogger("viral_analyzer")

LANGUAGES = ["English", "Spanish", "Hindi", "Nepali", "French", "Portuguese", "Arabic", "Japanese", "Korean"]
MIN_DUR, MAX_DUR = 20.0, 30.0
MARGIN = 0.05
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile")
GEMINI_MAX_CHARS = 350_000
GROQ_MAX_CHARS = int(os.getenv("GROQ_MAX_TRANSCRIPT_CHARS", "20000"))


class AnalysisError(Exception):
    pass


SYSTEM_PROMPT = """You are an expert viral short-form video editor for TikTok, YouTube Shorts, and Instagram Reels. Analyze this timestamped transcript and extract the top 3 most entertaining, funny, shocking, high-retention moments.

STRICT DURATION & PACING RULES
1. Every clip MUST be strictly between 20 and 30 seconds long: 20.0 <= (end_time - start_time) <= 30.0. Aim for 24-28 seconds.
2. THE 3-SECOND HOOK RULE: start each clip right before a high-energy statement, question, reaction, or pattern interrupt. Never start on dead air, filler words ("um", "so anyway"), or mid-sentence.
3. CLEAN ENDING: end on a punchline, realization, or complete thought so the clip loops seamlessly.
4. Clips must not overlap. start_time/end_time are seconds on the transcript's timeline and must fall on spoken-word boundaries.

NATURAL TRANSLATION & CHUNKING
1. Translate the spoken dialogue inside those exact timestamps into natural, conversational {TARGET_LANGUAGE}. Preserve slang, comedic timing, and emotional punch; never translate stiffly or literally.
2. Break the captions into punchy, fast-paced 2-to-4-word chunks synced to the exact audio timestamps (each chunk's start/end lies inside its clip, chunks are in order and never overlap, and together they cover all the speech in the clip).
3. "original_text" is what was actually said in the source language; "translated_text" is the {TARGET_LANGUAGE} version.

OUTPUT: respond with ONLY a JSON object, no markdown, no commentary, exactly this shape:
{"clips":[{"title":"short punchy hook title","virality_score":87,"editor_notes":"why this hook works","start_time":123.4,"end_time":148.9,"captions":[{"start":123.4,"end":125.1,"original_text":"...","translated_text":"..."}]}]}
virality_score is an integer from 1 to 100."""


# ---------- prompt / provider calls ----------

def _transcript_text(segments: list[dict], limit: int) -> str:
    lines, used = [], 0
    for s in segments:
        line = f"[{s['start']:.2f} - {s['end']:.2f}] {s['text'].strip()}"
        used += len(line) + 1
        if used > limit:
            break
        lines.append(line)
    return "\n".join(lines)


def _user_prompt(segments, language_hint, total, limit) -> str:
    return (
        f"Source language (detected): {language_hint or 'unknown'}\n"
        f"Total video length: {total:.1f} seconds\n\nTRANSCRIPT:\n{_transcript_text(segments, limit)}"
    )


def _call_gemini(system: str, user: str) -> str:
    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system, response_mime_type="application/json", temperature=0.7
        ),
    )
    return resp.text or ""


def _call_groq(system: str, user: str) -> str:
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=GROQ_LLM_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=0.6,
        max_tokens=4000,
    )
    return resp.choices[0].message.content or ""


def _extract_json(text: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a != -1 and b > a:
            return json.loads(t[a : b + 1])
        raise


# ---------- validation & repair ----------

def tokenize(text: str) -> tuple[list[str], str]:
    """Split into display tokens. Space-less scripts (ja/zh) are split into 2-char groups."""
    toks = text.split()
    if len(toks) <= 1 and len(text) > 4 and " " not in text:
        return [text[i : i + 2] for i in range(0, len(text), 2)], ""
    return toks, " "


def _split_even(items: list, n: int) -> list[list]:
    k, m = divmod(len(items), n)
    out, i = [], 0
    for j in range(n):
        step = k + (1 if j < m else 0)
        out.append(items[i : i + step])
        i += step
    return out


def _rechunk(start: float, end: float, orig: str, trans: str) -> list[dict]:
    """Guarantee 2-4 word chunks (splitting any longer chunk, timing proportional to text length)."""
    t_toks, t_sep = tokenize(trans)
    if len(t_toks) <= 4:
        return [{"start": start, "end": end, "original_text": orig, "translated_text": trans}]
    n = math.ceil(len(t_toks) / 4)
    t_groups = [t_sep.join(g) for g in _split_even(t_toks, n)]
    o_toks, o_sep = tokenize(orig)
    o_groups = [o_sep.join(g) for g in _split_even(o_toks, n)] if o_toks else [""] * n
    weights = [max(1, len(g)) for g in t_groups]
    total_w, cur, out = sum(weights), start, []
    for g, o, w in zip(t_groups, o_groups, weights):
        nxt = cur + (end - start) * w / total_w
        out.append({"start": cur, "end": nxt, "original_text": o, "translated_text": g})
        cur = nxt
    return out


def _captions_from_words(words: list[dict], s: float, e: float, per: int = 3) -> list[dict]:
    inside = [w for w in words if w["start"] >= s - 0.01 and w["end"] <= e + 0.01 and w["word"]]
    caps = []
    for i in range(0, len(inside), per):
        g = inside[i : i + per]
        text = " ".join(w["word"] for w in g)
        caps.append({"start": g[0]["start"], "end": g[-1]["end"], "original_text": text, "translated_text": text})
    return caps


def _normalize_captions(raw_caps, s: float, e: float) -> list[dict]:
    out = []
    for c in raw_caps or []:
        try:
            cs, ce = max(s, float(c["start"])), min(e, float(c["end"]))
        except (KeyError, TypeError, ValueError):
            continue
        orig = str(c.get("original_text") or "").strip()
        trans = str(c.get("translated_text") or "").strip() or orig
        if ce - cs < 0.15 or not trans:
            continue
        out.extend(_rechunk(cs, ce, orig, trans))
    out.sort(key=lambda c: c["start"])
    fixed, prev_end = [], s
    for c in out:
        c["start"] = max(c["start"], prev_end)
        if c["end"] - c["start"] < 0.1:
            continue
        c["start"], c["end"] = round(c["start"], 2), round(c["end"], 2)
        prev_end = c["end"]
        fixed.append(c)
    return fixed


def _fit_window(start, end, starts, ends, total):
    """Snap to spoken-word boundaries and force 20 < duration < 30. Returns (s, e) or None."""
    s = max(0.0, min(starts, key=lambda t: abs(t - start)) if starts else start)
    lo, hi = s + MIN_DUR + MARGIN, s + MAX_DUR - MARGIN
    if total:
        if lo > total:
            return None
        hi = min(hi, total)
    e = min(max(end, lo), hi)
    cands = [x for x in ends if lo <= x <= hi]
    if cands:
        e = min(cands, key=lambda x: abs(x - e))
    s, e = round(s, 2), round(e, 2)
    return (s, e) if MIN_DUR <= e - s <= MAX_DUR else None


def _overlaps(a, b) -> bool:
    inter = min(a["end_time"], b["end_time"]) - max(a["start_time"], b["start_time"])
    return inter > 0.3 * min(a["end_time"] - a["start_time"], b["end_time"] - b["start_time"])


def _postprocess(raw, words, segments, total, max_clips) -> list[dict]:
    items = raw.get("clips") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    starts = [w["start"] for w in words] or [s["start"] for s in segments]
    ends = [w["end"] for w in words] or [s["end"] for s in segments]
    clips = []
    for it in items:
        try:
            fit = _fit_window(float(it["start_time"]), float(it["end_time"]), starts, ends, total)
        except (KeyError, TypeError, ValueError):
            continue
        if not fit:
            continue
        s, e = fit
        caps = _normalize_captions(it.get("captions"), s, e)
        covered = sum(c["end"] - c["start"] for c in caps)
        if covered < 0.4 * (e - s):  # model skipped too much speech: rebuild from real word timings
            caps = _captions_from_words(words, s, e)
        if not caps:
            continue
        try:
            score = int(max(1, min(100, float(it.get("virality_score", 50)))))
        except (TypeError, ValueError):
            score = 50
        clips.append({
            "title": str(it.get("title") or "Untitled clip")[:90],
            "virality_score": score,
            "editor_notes": str(it.get("editor_notes") or "")[:500],
            "start_time": s,
            "end_time": e,
            "duration": round(e - s, 2),
            "captions": caps,
        })
    clips.sort(key=lambda c: c["virality_score"], reverse=True)
    chosen = []
    for c in clips:
        if not any(_overlaps(c, o) for o in chosen):
            chosen.append(c)
    return chosen[:max_clips]


def _heuristic(words, segments, total, max_clips) -> list[dict]:
    """No-LLM fallback: densest, most punctuated ~25 s windows. Captions stay in the source language."""
    starts = [w["start"] for w in words] or [s["start"] for s in segments]
    ends = [w["end"] for w in words] or [s["end"] for s in segments]
    scored = []
    for seg in segments:
        fit = _fit_window(seg["start"], seg["start"] + 25, starts, ends, total)
        if not fit:
            continue
        s, e = fit
        text = " ".join(x["text"] for x in segments if x["start"] >= s and x["end"] <= e)
        score = len(text.split()) / (e - s) + 0.4 * sum(text.count(ch) for ch in "?!")
        scored.append((score, s, e))
    scored.sort(reverse=True)
    items = [
        {"title": f"Highlight {i + 1}", "virality_score": max(30, 70 - 8 * i), "start_time": s, "end_time": e,
         "editor_notes": "Picked by the offline fallback (no LLM available): high speech density and energy.",
         "captions": []}
        for i, (_, s, e) in enumerate(scored[: max_clips * 4])
    ]
    return _postprocess(items, words, segments, total, max_clips)


# ---------- public API ----------

def find_viral_clips(transcript: dict, target_language: str, video_duration: float, max_clips: int = 3) -> list[dict]:
    if target_language not in LANGUAGES:
        raise AnalysisError(f"Unsupported target language: {target_language}")
    segments, words = transcript["segments"], transcript["words"]
    system = SYSTEM_PROMPT.replace("{TARGET_LANGUAGE}", target_language)
    lang = transcript.get("language")

    providers = []
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        providers.append(("gemini", _call_gemini, GEMINI_MAX_CHARS))
    if os.getenv("GROQ_API_KEY"):
        providers.append(("groq", _call_groq, GROQ_MAX_CHARS))

    errors = []
    for name, fn, limit in providers:
        try:
            text = fn(system, _user_prompt(segments, lang, video_duration, limit))
            clips = _postprocess(_extract_json(text), words, segments, video_duration, max_clips)
            if clips:
                log.info("Analyzer used %s -> %d clips", name, len(clips))
                return clips
            errors.append(f"{name}: no valid 20-30s clips returned")
        except Exception as exc:  # rate limits, bad JSON, network, etc. -> try next provider
            errors.append(f"{name}: {exc}")
            log.warning("LLM provider %s failed: %s", name, exc)

    clips = _heuristic(words, segments, video_duration, max_clips)
    if clips:
        log.warning("Using heuristic fallback (%s)", "; ".join(errors) or "no API keys configured")
        return clips
    raise AnalysisError("Could not find any 20-30 second clip. " + "; ".join(errors))

"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ChevronDown, Download, Flame, Loader2, RefreshCw } from "lucide-react";
import { API_URL, CaptionStyle, Clip, Layout, rerenderClip } from "@/lib/api";

interface Props {
  jobId: string;
  clip: Clip;
  defaultStyle: CaptionStyle;
  layout: Layout;
  onUpdated: (clip: Clip) => void;
}

const fmt = (t: number) => `${Math.floor(t / 60)}:${Math.floor(t % 60).toString().padStart(2, "0")}`;

function scoreTone(score: number) {
  if (score >= 80) return "bg-emerald-500/15 text-emerald-300 border-emerald-500/40";
  if (score >= 60) return "bg-amber-500/15 text-amber-300 border-amber-500/40";
  return "bg-zinc-700/40 text-zinc-300 border-zinc-600";
}

export default function ClipCard({ jobId, clip, defaultStyle, layout, onUpdated }: Props) {
  const [open, setOpen] = useState(false);
  const [edits, setEdits] = useState<string[]>(clip.captions.map((c) => c.translated_text));
  const [style, setStyle] = useState<CaptionStyle>(defaultStyle);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset the editor whenever the server returns a new render of this clip.
  useEffect(() => {
    setEdits(clip.captions.map((c) => c.translated_text));
  }, [clip.revision, clip.captions]);

  const rendering = busy || clip.status === "rendering" || clip.status === "pending";
  const dirty = edits.some((t, i) => t !== clip.captions[i]?.translated_text) || style !== defaultStyle;

  async function handleRerender() {
    setBusy(true);
    setError(null);
    try {
      const updated = await rerenderClip(jobId, clip.id, {
        captions: edits.map((t, i) => ({ index: i, translated_text: t })),
        caption_style: style,
        layout,
      });
      onUpdated(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-render failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="flex flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/70">
      <div className="relative mx-auto aspect-[9/16] w-full max-w-[340px] bg-black">
        {clip.status === "done" && clip.video_url ? (
          <video
            key={clip.video_url}
            src={`${API_URL}${clip.video_url}`}
            controls
            playsInline
            loop
            preload="metadata"
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-2 p-4 text-center text-sm text-zinc-400">
            {clip.status === "failed" ? (
              <>
                <AlertTriangle className="h-6 w-6 text-red-400" />
                <span>{clip.error || "Rendering failed"}</span>
              </>
            ) : (
              <>
                <Loader2 className="h-6 w-6 animate-spin text-fuchsia-400" />
                <span>Rendering clip…</span>
              </>
            )}
          </div>
        )}
        {busy && clip.status === "done" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/70 text-sm">
            <Loader2 className="h-6 w-6 animate-spin text-fuchsia-400" />
            Re-rendering captions…
          </div>
        )}
        <span className={`absolute left-3 top-3 flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold backdrop-blur ${scoreTone(clip.virality_score)}`}>
          <Flame className="h-3.5 w-3.5" />
          {clip.virality_score}
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <h3 className="text-base font-semibold leading-snug text-zinc-50">{clip.title}</h3>
          <p className="mt-0.5 text-xs text-zinc-500">
            {fmt(clip.start_time)} – {fmt(clip.end_time)} · {clip.duration.toFixed(1)}s
          </p>
        </div>

        <div className="rounded-xl bg-zinc-800/50 p-3 text-sm text-zinc-300">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-fuchsia-300">AI editor&apos;s breakdown</p>
          {clip.editor_notes || "No notes provided."}
        </div>

        {clip.status === "done" && clip.download_url && (
          <a
            href={`${API_URL}${clip.download_url}`}
            download
            className="flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-fuchsia-600 to-pink-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-110"
          >
            <Download className="h-4 w-4" />
            Download MP4
          </a>
        )}

        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          disabled={clip.status !== "done"}
          className="flex items-center justify-between rounded-xl border border-zinc-700 px-4 py-2.5 text-sm text-zinc-200 transition hover:bg-zinc-800 disabled:opacity-40"
        >
          Quick caption editor
          <ChevronDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>

        {open && (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3 text-xs text-zinc-400">
              <span>Fix any translated word, then re-render.</span>
              <select
                value={style}
                onChange={(e) => setStyle(e.target.value as CaptionStyle)}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 text-zinc-200"
              >
                <option value="translated">Translated only</option>
                <option value="bilingual">Bilingual</option>
              </select>
            </div>

            <ul className="max-h-72 space-y-2 overflow-y-auto pr-1">
              {clip.captions.map((c, i) => (
                <li key={i} className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-2">
                  <div className="mb-1 flex items-center justify-between text-[11px] text-zinc-500">
                    <span className="tabular-nums">{fmt(c.start - clip.start_time)}</span>
                    <span className="max-w-[70%] truncate">{c.original_text}</span>
                  </div>
                  <input
                    value={edits[i] ?? ""}
                    maxLength={300}
                    onChange={(e) => setEdits((prev) => prev.map((t, j) => (j === i ? e.target.value : t)))}
                    className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100 outline-none focus:border-fuchsia-500"
                  />
                </li>
              ))}
            </ul>

            {error && <p className="text-xs text-red-400">{error}</p>}

            <button
              type="button"
              onClick={handleRerender}
              disabled={rendering || !dirty}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-zinc-100 px-4 py-2.5 text-sm font-semibold text-zinc-900 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Re-render Captions
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

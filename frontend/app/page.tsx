"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { AlertTriangle, Link2, Loader2, Radio, Scissors } from "lucide-react";
import ProgressTracker from "@/components/ProgressTracker";
import ClipCard from "@/components/ClipCard";
import { CaptionStyle, Clip, Job, LANGUAGES, Layout, createJob, getJob } from "@/lib/api";

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; text: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div>
      <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-zinc-400">{label}</span>
      <div className="flex rounded-xl border border-zinc-700 bg-zinc-900 p-1">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={`flex-1 rounded-lg px-3 py-2 text-sm transition ${
              value === o.value ? "bg-fuchsia-600 font-semibold text-white" : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            {o.text}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [language, setLanguage] = useState<string>("English");
  const [style, setStyle] = useState<CaptionStyle>("translated");
  const [layout, setLayout] = useState<Layout>("crop");
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const failures = useRef(0);

  // Poll job status every 1.5 s until it finishes or fails.
  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    failures.current = 0;

    const tick = async () => {
      try {
        const j = await getJob(jobId);
        if (stopped) return;
        failures.current = 0;
        setJob(j);
        if (j.status === "completed" || j.status === "failed") clearInterval(timer);
      } catch (e) {
        if (stopped) return;
        failures.current += 1;
        const message = e instanceof Error ? e.message : "Lost connection to the server";
        if (failures.current >= 5 || message.includes("expired")) {
          setError(message);
          clearInterval(timer);
        }
      }
    };
    const timer = setInterval(tick, 1500);
    tick();
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [jobId]);

  const processing =
    submitting || (!!jobId && !job && !error) || (!!job && (job.status === "queued" || job.status === "running"));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (processing) return;
    setError(null);
    setJob(null);
    setJobId(null);
    setSubmitting(true);
    try {
      const { job_id } = await createJob({ url: url.trim(), target_language: language, caption_style: style, layout });
      setJobId(job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the job");
    } finally {
      setSubmitting(false);
    }
  }

  function handleClipUpdated(updated: Clip) {
    setJob((prev) => (prev ? { ...prev, clips: prev.clips.map((c) => (c.id === updated.id ? updated : c)) } : prev));
  }

  const failedMessage = error || (job?.status === "failed" ? job.error || "Processing failed" : null);

  return (
    <main className="mx-auto max-w-6xl px-4 pb-24 pt-12 sm:px-6">
      <header className="mb-10 text-center">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-fuchsia-500/30 bg-fuchsia-500/10 px-3 py-1 text-xs font-medium text-fuchsia-300">
          <Scissors className="h-3.5 w-3.5" /> 100% free · open-source stack
        </div>
        <h1 className="text-4xl font-extrabold tracking-tight sm:text-6xl">
          Turn any YouTube video into{" "}
          <span className="bg-gradient-to-r from-fuchsia-400 via-pink-400 to-amber-300 bg-clip-text text-transparent">
            viral shorts
          </span>
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-zinc-400">
          Paste a video or live stream link. The AI editor finds the best 20-30 second hooks, crops them to 9:16, and
          burns in translated kinetic captions.
        </p>
      </header>

      <form onSubmit={onSubmit} className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4 shadow-2xl shadow-fuchsia-950/20 sm:p-6">
        <div className="relative">
          <Link2 className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-zinc-500" />
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=…  or  youtube.com/live/…"
            required
            className="w-full rounded-xl border border-zinc-700 bg-zinc-950 py-3.5 pl-12 pr-4 text-base outline-none placeholder:text-zinc-600 focus:border-fuchsia-500"
          />
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-zinc-400">
              Target caption language
            </span>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="w-full rounded-xl border border-zinc-700 bg-zinc-900 px-3 py-3 text-sm outline-none focus:border-fuchsia-500"
            >
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <Segmented
            label="Caption style"
            value={style}
            onChange={setStyle}
            options={[
              { value: "translated", text: "Translated only" },
              { value: "bilingual", text: "Bilingual" },
            ]}
          />
          <Segmented
            label="Video layout"
            value={layout}
            onChange={setLayout}
            options={[
              { value: "crop", text: "Center crop" },
              { value: "blur", text: "Blurred bg" },
            ]}
          />
        </div>

        <button
          type="submit"
          disabled={processing || !url.trim()}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-fuchsia-600 via-pink-600 to-amber-500 px-6 py-3.5 text-base font-bold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {processing ? <Loader2 className="h-5 w-5 animate-spin" /> : <Scissors className="h-5 w-5" />}
          {processing ? "Working on it…" : "Generate Free Clips"}
        </button>
      </form>

      {failedMessage && (
        <div className="mt-6 flex items-start gap-3 rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <span className="break-words">{failedMessage}</span>
        </div>
      )}

      {(job || processing) && !error && (
        <section className="mt-8 space-y-4">
          {job?.title && (
            <div className="flex flex-wrap items-center gap-2 text-sm text-zinc-300">
              {job.is_live && (
                <span className="inline-flex items-center gap-1 rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-semibold text-red-300">
                  <Radio className="h-3 w-3" /> LIVE
                </span>
              )}
              <span className="font-medium">{job.title}</span>
              {job.truncated && (
                <span className="text-xs text-zinc-500">
                  ({job.is_live ? "first 10 minutes of the live DVR buffer" : "first 90 minutes"} analysed)
                </span>
              )}
            </div>
          )}
          <ProgressTracker
            stage={job?.stage ?? 0}
            status={job?.status ?? "queued"}
            progress={job?.progress ?? 0}
          />
        </section>
      )}

      {job && job.clips.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-5 text-2xl font-bold">Your clips</h2>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {job.clips.map((clip) => (
              <ClipCard
                key={clip.id}
                jobId={job.id}
                clip={clip}
                defaultStyle={job.options.caption_style}
                layout={job.options.layout}
                onUpdated={handleClipUpdated}
              />
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

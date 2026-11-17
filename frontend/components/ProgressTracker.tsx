import { Check, Download, Film, Languages, Loader2, Mic, Sparkles, XCircle } from "lucide-react";

const STEPS = [
  { label: "Fetching Stream/Video", Icon: Download },
  { label: "Transcribing Audio", Icon: Mic },
  { label: "AI Editor Finding 20-30s Hooks", Icon: Sparkles },
  { label: "Translating & Styling Captions", Icon: Languages },
  { label: "Rendering 9:16 Clips", Icon: Film },
];

interface Props {
  stage: number; // 0 = queued, 1-5 = active stage
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
}

export default function ProgressTracker({ stage, status, progress }: Props) {
  const failed = status === "failed";
  const completed = status === "completed";

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5">
      <div className="mb-4 flex items-center justify-between text-sm">
        <span className="font-medium text-zinc-200">
          {completed ? "All done" : failed ? "Processing failed" : stage === 0 ? "Queued, waiting for a free worker…" : "Processing"}
        </span>
        <span className="tabular-nums text-zinc-400">{completed ? 100 : progress}%</span>
      </div>

      <div className="mb-5 h-2 overflow-hidden rounded-full bg-zinc-800">
        <div
          className={`h-full rounded-full transition-all duration-700 ${
            failed ? "bg-red-500" : "bg-gradient-to-r from-fuchsia-500 via-pink-500 to-amber-400"
          }`}
          style={{ width: `${completed ? 100 : progress}%` }}
        />
      </div>

      <ol className="grid gap-2 sm:grid-cols-5">
        {STEPS.map(({ label, Icon }, i) => {
          const n = i + 1;
          const done = completed || stage > n;
          const active = !completed && stage === n;
          const base = "flex items-start gap-2 rounded-xl border px-3 py-2.5 text-xs leading-snug transition-colors";
          const tone = done
            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
            : active && failed
              ? "border-red-500/40 bg-red-500/10 text-red-300"
              : active
                ? "border-fuchsia-500/50 bg-fuchsia-500/10 text-fuchsia-200"
                : "border-zinc-800 bg-zinc-900 text-zinc-500";
          return (
            <li key={label} className={`${base} ${tone}`}>
              <span className="mt-0.5 shrink-0">
                {done ? (
                  <Check className="h-4 w-4" />
                ) : active && failed ? (
                  <XCircle className="h-4 w-4" />
                ) : active ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Icon className="h-4 w-4" />
                )}
              </span>
              <span>
                {n}. {label}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

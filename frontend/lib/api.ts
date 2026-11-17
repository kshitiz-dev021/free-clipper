export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export const LANGUAGES = [
  "English", "Spanish", "Hindi", "Nepali", "French", "Portuguese", "Arabic", "Japanese", "Korean",
] as const;

export type CaptionStyle = "translated" | "bilingual";
export type Layout = "crop" | "blur";

export interface Caption {
  start: number;
  end: number;
  original_text: string;
  translated_text: string;
}

export interface Clip {
  id: string;
  title: string;
  virality_score: number;
  editor_notes: string;
  start_time: number;
  end_time: number;
  duration: number;
  captions: Caption[];
  status: "pending" | "rendering" | "done" | "failed";
  error: string | null;
  revision: number;
  video_url: string | null;
  download_url: string | null;
}

export interface Job {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: number;
  stage_label: string;
  progress: number;
  error: string | null;
  title: string | null;
  is_live: boolean;
  truncated: boolean;
  options: { url: string; target_language: string; caption_style: CaptionStyle; layout: Layout };
  clips: Clip[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const createJob = (body: {
  url: string;
  target_language: string;
  caption_style: CaptionStyle;
  layout: Layout;
}) => request<{ job_id: string }>("/api/jobs", { method: "POST", body: JSON.stringify(body) });

export const getJob = (id: string) => request<Job>(`/api/jobs/${id}`);

export const rerenderClip = (
  jobId: string,
  clipId: string,
  body: {
    captions: { index: number; translated_text: string }[];
    caption_style?: CaptionStyle;
    layout?: Layout;
  },
) =>
  request<Clip>(`/api/jobs/${jobId}/clips/${clipId}/rerender`, {
    method: "POST",
    body: JSON.stringify(body),
  });

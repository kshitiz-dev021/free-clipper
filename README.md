# FreeClipper

A web-based AI video clipper. Paste a supported YouTube video/Live URL, find highlight moments, generate vertical clips, and download them.

## Free deployment (no Docker installation on your Mac)

This project is configured for:

- **Frontend:** Vercel Hobby (Next.js, free for personal projects)
- **Backend:** Render Free Web Service using the included Dockerfile
- **AI:** Optional Gemini and Groq API keys on their free tiers
- **Fallback:** local `faster-whisper` tiny model and offline clip-selection heuristic

Cloud providers build and run the Docker container. You do not need Docker installed locally.

> Free hosting is limited, not unlimited. Render free services have 512 MB RAM, spin down after 15 minutes without traffic, and use an ephemeral filesystem. Video processing may be slow or fail for large videos. Generated files are temporary; download clips promptly. The tiny Whisper fallback is intentionally selected to reduce memory use, but can still be constrained on the free instance.

## 1. Protect your API keys

Never commit `.env`, `.env.local`, API keys, or YouTube cookies. The root `.gitignore` excludes them. If a key was ever shared or committed, revoke it and create a replacement.

Create free API keys if you want AI-assisted processing:

- Gemini: https://aistudio.google.com/apikey
- Groq: https://console.groq.com/keys

The app can run without either key: local transcription and the offline clip-selection heuristic are used. Groq is recommended for transcription; Gemini is tried first for clip selection, then Groq, then the offline heuristic.

## 2. Push this clean project to GitHub

1. Create a new GitHub repository.
2. Upload the contents of this folder (the files inside `free-clipper`, not the enclosing ZIP folder).
3. Confirm `.env` is not in the repository. Do not upload any API keys.

## 3. Deploy the backend on Render

1. Sign in at https://render.com using GitHub.
2. Choose **New → Web Service**, then connect this repository.
3. Select **Docker** as the runtime if asked; use the repository root as the Root Directory.
4. Choose the **Free** instance type.
5. Set these environment variables in Render:
   - `GROQ_API_KEY` = your Groq key (optional but recommended)
   - `GEMINI_API_KEY` = your Gemini key (optional)
   - `WHISPER_MODEL` = `tiny`
   - `TRANSCRIBER` = `auto`
   - `MAX_CONCURRENT_JOBS` = `1`
   - `JOB_TTL_SECONDS` = `7200`
   - `DATA_DIR` = `/tmp/freeclipper`
6. Deploy. Wait for the service to become Live.
7. Copy the service URL, for example `https://freeclipper-api.onrender.com`.
8. Test `https://YOUR-RENDER-URL/api/health` in a browser. It should return JSON with `"ok": true`.

The included `render.yaml` is an optional Blueprint configuration. You can instead create the Web Service manually using the steps above.

## 4. Deploy the frontend on Vercel

1. Sign in at https://vercel.com with GitHub.
2. Import the same repository.
3. Set **Root Directory** to `frontend`.
4. Set the environment variable:
   - `NEXT_PUBLIC_API_URL` = your Render backend URL, with no trailing slash.
5. Deploy and copy the Vercel URL.

## 5. Connect the frontend to the backend

In Render → your service → **Environment**, add:

- `FRONTEND_ORIGINS` = your exact Vercel URL (for example `https://freeclipper.vercel.app`, no trailing slash)

Save changes and redeploy/restart the Render service. Then open the Vercel website and test a short public video first.

## Free-hosting limitations

- Render Free Web Services sleep after 15 minutes of inactivity and take around a minute to wake up.
- Render free instances have 512 MB RAM and ephemeral storage. Files disappear on restart, redeploy, or spin-down.
- Render includes 750 free instance hours per workspace per month. Free services can be suspended after included usage is exhausted.
- Vercel Hobby is intended for personal, non-commercial projects and has usage limits.
- Gemini and Groq free API limits vary by model and can change. If an API reaches its limit, the app tries its fallback path.
- YouTube may block downloads from datacenter IP addresses. Some videos may not be downloadable from the hosted backend.
- Always download finished clips promptly; this project cleans job files after two hours.

## Local development

See `.env.example` and `frontend/.env.local.example`. You can run the Python backend and Next.js frontend locally without Docker if Python, FFmpeg, and Node.js are installed.
# free-clipper

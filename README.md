# Astrometry Console — web app

A full-stack web front-end for the astronomy detection pipeline.

```
Browser ──► Next.js + React (Tailwind)  ──►  FastAPI (Python)  ──►  pipeline.py
 upload        localhost:3000                  localhost:8000        DAO + auto-FWHM
 sliders       upload form, sliders,           POST /analyze         + saturated pass
               results table + image           returns JSON + PNG    + 5-catalog match
```

Two apps run side by side: a **Python API** that wraps the pipeline, and a
**Next.js UI** that calls it. They talk over HTTP on localhost.

---

## Prerequisites
- Python 3.10+  (for the backend)
- Node.js 18+   (for the frontend)

---

## 1. Backend (FastAPI)

```bash
cd backend
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn api:app --reload --port 8000
```

Check it: open http://localhost:8000/health → `{"status":"ok"}`.

**Demo mode** — run the UI with no FITS file and no network (synthetic results):
```bash
# macOS/Linux
DEMO_MODE=1 uvicorn api:app --reload --port 8000
# Windows PowerShell
$env:DEMO_MODE=1; uvicorn api:app --reload --port 8000
```

`pipeline.py` is your consolidated notebook (load → preprocess → auto-FWHM
detection → saturated-star pass → plate solve → Gaia/SIMBAD/Pan-STARRS/NED/
SkyBoT cross-match → annotated PNG). `api.py` just calls `run_pipeline`.

---

## 2. Frontend (Next.js + Tailwind)

```bash
cd frontend
npm install
cp .env.local.example .env.local      # sets NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open http://localhost:3000.

---

## Using it
1. Start the backend, then the frontend.
2. Choose a FITS file (or leave empty + run backend in DEMO_MODE to preview).
3. Adjust FWHM / threshold / match radius, toggle auto-FWHM.
4. **Run detection** → the annotated image and object table appear, with counts
   for detected / known / new. Coordinates are shown in monospace; each object
   is tagged known (green, with the catalog that matched) or new (red).

---

## Notes
- The browser calls FastAPI directly; CORS is already allowed for
  `localhost:3000` in `api.py` (add your deployed origin there later).
- Catalog queries (Gaia/SIMBAD/etc.) need internet. If a service is
  unreachable, that catalog is skipped and matching still returns positions.
- Large FITS + plate solving + catalog queries can take many seconds; the UI
  shows a working state while it runs.
- To deploy: host FastAPI (e.g. Render/Fly/a VM) and the Next.js app
  (e.g. Vercel), then point `NEXT_PUBLIC_API_URL` at the deployed API.

---

## Docker (single container, port 3004)

Both the frontend and backend run in **one** container. Only **port 3004** is
exposed — the browser hits the Next.js server there, and it proxies `/api/*` to
the backend running internally on port 8000.

**Build & run with docker compose:**
```bash
docker compose up --build
```
Then open **http://localhost:3004**.

**Or with plain Docker:**
```bash
docker build -t astro-web .
docker run -p 3004:3004 astro-web
```

**Demo mode** (synthetic results, no FITS / no network) — uncomment the
`DEMO_MODE=1` line in `docker-compose.yml`, or:
```bash
docker run -p 3004:3004 -e DEMO_MODE=1 astro-web
```

Notes:
- The image includes the astronomy stack (astropy, photutils, astroquery,
  scipy), so the first build takes a few minutes and the image is on the
  larger side.
- Real catalog queries (Gaia / SIMBAD / …) and astrometry.net still need the
  container to have internet access.

---

## Push to a new GitHub repo

From the project root (`astro-web/`):
```bash
git init
git add .
git commit -m "Astrometry Console: FITS detection + catalog cross-match web app"
git branch -M main
```
Create an empty repo on GitHub (no README/license), then:
```bash
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```
`node_modules/`, `.next/`, `venv/`, `__pycache__/`, and `.env.local` are already
excluded via `.gitignore`.

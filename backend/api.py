"""
api.py — FastAPI wrapper around the astronomy pipeline.

  GET  /health   -> {"status": "ok"}
  POST /analyze  -> run the pipeline on an uploaded FITS. Returns JSON:
                    counts, object table, a clean base image (for the
                    interactive overlay) + its pixel dimensions, and the
                    annotated PNG (for download).

Run:  python -m uvicorn api:app --reload --port 8000
Demo: set DEMO_MODE=1 first (synthetic results, no FITS / no network).
"""
import os, io, base64, tempfile, traceback, time, uuid
import numpy as np

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import pipeline

# Server data root. On the server this is the mounted /mnt/store/MEW; each run
# gets its own subfolder here (input FITS + outputs persist). Falls back to a
# system temp dir when the path isn't available (e.g. local dev), so nothing
# breaks off the server. Override with the DATA_DIR env var.
DATA_DIR = os.environ.get("DATA_DIR", "/mnt/store/MEW")


def _make_work_dir():
    """A writable per-run folder under DATA_DIR, or a temp dir as fallback."""
    try:
        runs = os.path.join(DATA_DIR, "runs")
        os.makedirs(runs, exist_ok=True)
        d = os.path.join(runs, time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
        os.makedirs(d, exist_ok=True)
        return d
    except Exception as exc:
        print(f"DATA_DIR '{DATA_DIR}' not usable ({exc}); using a temp dir.")
        return tempfile.mkdtemp()

app = FastAPI(title="Astro Pipeline API", version="1.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "demo_mode": os.environ.get("DEMO_MODE") == "1",
            "data_dir": DATA_DIR, "data_dir_writable": os.access(DATA_DIR, os.W_OK)}


def _png_to_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _demo_payload():
    """Synthetic result incl. a base image + overlay coords, so the UI's
    interactive view and downloads work without a FITS or network."""
    from PIL import Image
    W = H = 520
    rng = np.random.default_rng(7)
    # faint noisy background with a few bright blobs = a believable base image
    img = rng.normal(28, 10, (H, W))
    n = 60
    xs, ys = rng.uniform(20, W - 20, n), rng.uniform(20, H - 20, n)
    known = rng.random(n) > 0.08
    yy, xx = np.mgrid[0:H, 0:W]
    for i in range(n):
        amp = rng.uniform(60, 200)
        img += amp * np.exp(-(((xx - xs[i])**2 + (yy - ys[i])**2) / (2 * 2.2**2)))
    img8 = np.clip((img - img.min()) / max(float(np.ptp(img)), 1e-6) * 255, 0, 255).astype(np.uint8)
    buf = io.BytesIO(); Image.fromarray(img8, mode="L").save(buf, format="PNG")
    base_png = base64.b64encode(buf.getvalue()).decode("ascii")

    objects = []
    for i in range(n):
        k = bool(known[i])
        objects.append({
            "x": round(float(xs[i]), 2), "y": round(float(ys[i]), 2),
            "ra": round(float(206.5 + xs[i] * 1e-4), 6),
            "dec": round(float(-2.7 - ys[i] * 1e-4), 6),
            "flux": round(float(rng.uniform(200, 9000)), 1),
            "status": "known" if k else "new",
            "matched_by": (str(rng.choice(["Gaia_DR3", "PanSTARRS", "SIMBAD"]))
                           if k else None),
        })
    nk = sum(1 for o in objects if o["status"] == "known")
    return {
        "ok": True, "demo": True,
        "counts": {"detected": n, "known": nk, "new": n - nk},
        "fwhm_used": 3.4, "wcs_ok": True, "solver_used": "demo",
        "object_name": "DEMO FIELD", "pixel_scale": 1.6356, "fov_arcmin": 27.91,
        "objects": objects,
        "base_image_png": base_png, "img_width": W, "img_height": H,
        "image_png_base64": base_png,   # download uses the same in demo
    }


@app.post("/analyze")
async def analyze(
    file: UploadFile = File(None),
    fwhm: float = Form(3.0),
    auto_fwhm: bool = Form(True),
    threshold_sigma: float = Form(5.0),
    search_radius: float = Form(30.0),
    api_key: str = Form(None),
    scale_hint: float = Form(None),
    solver: str = Form("auto"),
    use_dao: bool = Form(True),
    use_tetra3: bool = Form(False),
    tetra_sigma: float = Form(5.0),
    tetra_min_area: int = Form(5),
    use_gaia: bool = Form(True),
    use_simbad: bool = Form(True),
    use_panstarrs: bool = Form(True),
    use_ned: bool = Form(True),
    use_skybot: bool = Form(True),
):
    if os.environ.get("DEMO_MODE") == "1" or file is None:
        return JSONResponse(_demo_payload())

    work = _make_work_dir()
    fits_path = os.path.join(work, file.filename or "upload.fits")
    out_png = os.path.join(work, "annotated.png")
    with open(fits_path, "wb") as f:
        f.write(await file.read())

    try:
        r = pipeline.run_pipeline(
            fits_path, out_png,
            fwhm=fwhm, auto_fwhm=auto_fwhm, threshold_sigma=threshold_sigma,
            search_radius=search_radius,
            api_key=api_key, scale_hint=scale_hint, solver=solver,
            use_dao=use_dao, use_tetra3=use_tetra3,
            tetra_sigma=tetra_sigma, tetra_min_area=tetra_min_area,
            use_gaia=use_gaia, use_simbad=use_simbad, use_panstarrs=use_panstarrs,
            use_ned=use_ned, use_skybot=use_skybot,
        )
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                            status_code=400)

    return JSONResponse({
        "ok": True, "demo": False,
        "counts": {"detected": r["n_sources"], "known": r["n_known"], "new": r["n_new"]},
        "fwhm_used": r["fwhm_used"], "wcs_ok": r["wcs_ok"],
        "solver_used": r.get("solver_used"),
        "center_source": r.get("center_source"),
        "object_name": r.get("object_name"),
        "pixel_scale": r.get("pixel_scale"),
        "fov_arcmin": r.get("fov_arcmin"),
        "objects": r["objects"],
        "base_image_png": r["base_image_png"],
        "img_width": r["img_width"], "img_height": r["img_height"],
        "image_png_base64": _png_to_b64(out_png) if os.path.exists(out_png) else r["base_image_png"],
    })

"""
pipeline.py — your astronomy pipeline as an importable module.

Extracted from astro_pipeline_gaia_wcs_2.ipynb with a run_pipeline() driver
added so a web API can run the whole thing in one call. The science functions
are your tested notebook code, unchanged.
"""

import os
import time
import warnings
import csv

import numpy as np
import matplotlib
matplotlib.use("Agg")          # headless backend; swap to 'inline' if preferred
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

warnings.filterwarnings("ignore")

# ── Astropy ──────────────────────────────────────────────────────────────
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning
from astropy.wcs.utils import fit_wcs_from_points
from astropy.coordinates import SkyCoord
from astropy.time import Time
import astropy.units as u
from astropy.table import Table
from astropy.visualization import ZScaleInterval, ImageNormalize

warnings.filterwarnings("ignore", category=FITSFixedWarning)

# ── Astroquery ───────────────────────────────────────────────────────────
from astroquery.simbad import Simbad
from astroquery.vizier import Vizier

# ── Photutils ────────────────────────────────────────────────────────────
from photutils.detection import DAOStarFinder
from photutils.background import Background2D, MedianBackground

# ── Plate solving (offline Gaia DR3; astrometry.net removed) ─────────────
from scipy.spatial import cKDTree    # astroquery.gaia.Gaia is imported lazily in plate_solve


C_DAO   = "#00BFFF"
C_KNOWN = "#00FF88"
C_NEW   = "#FF3B3B"

# Offline-Gaia plate-solve matching config (from the notebook).
GAIA_CFG = dict(
    gaia_maglimit      = 14.0,   # faintest Gaia G to fetch for the solve
    gaia_radius_factor = 0.9,    # cone radius = factor × FOV (deg)
    n_match_gaia       = 200,    # Gaia stars considered when matching
    n_det_match        = 60,     # brightest DETECTED stars used for the pattern lock
                                 # (cost is quadratic in this; keep <= n_match_gaia)
    len_tol_px         = 2.0,    # absolute pair-length tolerance (px)
    len_rel_tol        = 0.03,   # relative pair-length tolerance (~3% scale)
    rot_bin_deg        = 0.5,    # rotation-vote bin size
    coarse_tol_px      = 4.0,    # inlier tolerance when assigning to Gaia
)


def load_fits(fits_path: str):
    """Load image + WCS. Returns (data, header, wcs | None)."""
    print(f"Loading: {fits_path}")

    with fits.open(fits_path) as hdul:
        data, header = None, None
        for hdu in hdul:
            if hdu.data is not None and hdu.data.ndim >= 2:
                data, header = hdu.data.astype(np.float64), hdu.header
                break
        if data is None:
            raise ValueError("No 2-D image found in the FITS file.")
        while data.ndim > 2:
            data = data[0]

    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

    wcs = None
    try:
        w = WCS(header, naxis=2)
        if w.has_celestial:
            wcs = w
            cy, cx = np.array(data.shape) / 2
            c = wcs.pixel_to_world(cx, cy)
            print(f"  Shape  : {data.shape[1]} × {data.shape[0]} px")
            print(f"  Center : RA {c.ra.deg:.5f}°, DEC {c.dec.deg:+.5f}°")
        else:
            print("  ⚠  WCS has no celestial axes.")
    except Exception as exc:
        print(f"  ⚠  WCS parse failed: {exc}")
    return data, header, wcs


def preprocess(data: np.ndarray, box_size: int = 64):
    """Subtract 2-D sky background. Returns (subtracted, rms)."""
    print("Estimating and subtracting sky background …")
    try:
        bkg = Background2D(data, (box_size, box_size), filter_size=(3, 3),
                           bkg_estimator=MedianBackground())
        sub = data - bkg.background
        rms = float(np.median(bkg.background_rms))
        print(f"  Median sky : {np.median(bkg.background):.2f}")
        print(f"  Median RMS : {rms:.4f}")
    except Exception as exc:
        print(f"  Background2D failed ({exc}); using global median.")
        sub = data - np.median(data); rms = float(np.std(sub))
    return sub, rms


from photutils.morphology import data_properties

def estimate_fwhm(sub, rms, guess_fwhm=3.0, n_sigma=8.0, n_stars=15, box=7):
    """Measure the median FWHM (px) from bright, isolated stars in THIS image.

    Two-pass: a rough high-threshold detection finds clean bright stars, then a
    moment-based width (2.355 x sigma) is measured on each and the median taken.
    Returns guess_fwhm if nothing usable is found, so it can never crash a run.
    """
    finder = DAOStarFinder(fwhm=guess_fwhm, threshold=n_sigma*rms, exclude_border=True)
    src = finder(sub)
    if src is None or len(src) == 0:
        print(f"  estimate_fwhm: no bright stars at {n_sigma}sigma -> using {guess_fwhm}")
        return guess_fwhm
    src = Table(src)
    for o, n in {"x_centroid": "xcentroid", "y_centroid": "ycentroid"}.items():
        if o in src.colnames and n not in src.colnames:
            src.rename_column(o, n)
    src.sort("peak"); src.reverse()                 # brightest first
    fwhms = []
    H, W = sub.shape
    for r in src[:n_stars*3]:                        # scan a few extra for rejects
        x, y = int(round(r["xcentroid"])), int(round(r["ycentroid"]))
        if x-box < 0 or y-box < 0 or x+box+1 > W or y+box+1 > H:
            continue
        cut = sub[y-box:y+box+1, x-box:x+box+1]
        try:
            p = data_properties(cut - np.median(cut))
            f = 2.355*np.sqrt(p.semimajor_sigma.value * p.semiminor_sigma.value)
            if np.isfinite(f) and 1.0 < f < 20.0:    # sane stars only
                fwhms.append(f)
        except Exception:
            continue
        if len(fwhms) >= n_stars:
            break
    if not fwhms:
        return guess_fwhm
    fwhm = float(np.median(fwhms))
    print(f"  estimate_fwhm: measured {fwhm:.2f} px from {len(fwhms)} stars")
    return fwhm

def detect_sources(sub: np.ndarray, rms: float,
                   fwhm: float = 3.0, n_sigma: float = 5.0,
                   sharplo=0.2, sharphi=1.0, roundlo=-1.0, roundhi=1.0):
    """Detect point sources with DAOStarFinder. Returns a Table or None."""
    print(f"DAOStarFinder  FWHM={fwhm:.2f} px, threshold={n_sigma}sigma, "
          f"sharp=[{sharplo},{sharphi}] round=[{roundlo},{roundhi}] ...")
    finder  = DAOStarFinder(fwhm=fwhm, threshold=n_sigma * rms,
                            sharplo=sharplo, sharphi=sharphi,
                            roundlo=roundlo, roundhi=roundhi,
                            exclude_border=True)
    sources = finder(sub)

    # Normalise column names across photutils versions (>=3.0 uses x_centroid).
    if sources is not None:
        sources = Table(sources)
        for old, new in {"x_centroid": "xcentroid",
                         "y_centroid": "ycentroid",
                         "n_pixels":   "npix"}.items():
            if old in sources.colnames and new not in sources.colnames:
                sources.rename_column(old, new)

    n = len(sources) if sources is not None else 0
    print(f"  Sources detected: {n}")
    return sources

from scipy import ndimage

def detect_saturated(sub, rms, sat_frac=0.6, sat_sigma=20.0, sat_level=None,
                     min_pixels=6, max_axis_ratio=2.0,
                     existing=None, dedup_radius=8.0):
    """Recover flat-topped SATURATED stars that DAOStarFinder structurally
    rejects (a flat core fails its sharpness test).

    Thresholds the brightest pixels (above sat_frac x image-max, or sat_level),
    labels connected blobs, and returns each blob's intensity-weighted centroid
    + peak.  Safe against:
      - hot pixels      -> min_pixels floor
      - streaks/trails  -> orientation-independent axis-ratio (covariance) cut
      - duplicates      -> skips blobs already found by DAOStarFinder
    Returns a Table (xcentroid/ycentroid/peak) or None.
    """
    if sat_level is None:
        sat_level = max(sat_sigma*rms, sat_frac*float(np.nanmax(sub)))
    mask = sub > sat_level
    if not mask.any():
        return None
    labels, n = ndimage.label(mask)
    slices = ndimage.find_objects(labels)

    ex = None
    if existing is not None and len(existing) > 0:
        ex = np.array([[float(r["xcentroid"]), float(r["ycentroid"])]
                       for r in existing])

    rows = []
    for lab, sl in enumerate(slices, start=1):
        if sl is None:
            continue
        region = labels[sl] == lab
        npix = int(region.sum())
        if npix < min_pixels:                       # hot-pixel speck
            continue
        yidx, xidx = np.nonzero(region)
        coords = np.vstack([xidx.astype(float), yidx.astype(float)])
        coords -= coords.mean(axis=1, keepdims=True)
        if npix >= 3:
            ev = np.linalg.eigvalsh(np.cov(coords)); ev = np.clip(ev, 1e-6, None)
            axis_ratio = float(np.sqrt(ev[-1] / ev[0]))
        else:
            axis_ratio = 1.0
        if axis_ratio > max_axis_ratio:             # streak / trail, not a star
            continue
        ys0, xs0 = sl
        sub_reg = sub[sl]
        yy, xx = np.mgrid[ys0.start:ys0.stop, xs0.start:xs0.stop]
        wint = np.where(region, sub_reg, 0.0); tot = wint.sum()
        cx = (xx*wint).sum()/tot; cy = (yy*wint).sum()/tot
        pk = float(sub_reg[region].max())
        if ex is not None and len(ex) and \
                np.hypot(ex[:, 0]-cx, ex[:, 1]-cy).min() < dedup_radius:
            continue                                # already caught by DAOStarFinder
        rows.append((cx, cy, pk))

    if not rows:
        return None
    return Table(rows=rows, names=("xcentroid", "ycentroid", "peak"))


def plate_solve(stars, fits_path, cfg=None, pixel_scale=None,
                verbose=True, center_override=None):
    """Offline plate solve: match detected star centroids to Gaia DR3 (no astrometry.net).

    Ported from wcs_from_top5_4.ipynb and folded into one self-contained function.
    Header reading, the Gaia cone query, the flip/rotation/shift lock, full-field
    matching, refinement and the final TAN-WCS fit all live here.

    stars       : (N,3) array [X, Y, FLUX]  (0-indexed pixel coords, brightest first or any order)
    fits_path   : path to the FITS, read for the header centre + pixel scale
    cfg         : matching-config dict (defaults to GAIA_CFG)
    pixel_scale : arcsec/px override; if None, derived from XPIXSZ (um) & FOCALLEN (mm),
                  else from a PIXSCALE/SECPIX/SCALE header key if present

    Returns (wcs, meta) on success, or (None, meta).
    """
    from itertools import combinations
    if cfg is None:
        cfg = GAIA_CFG

    # ---- nested helper: approximate field centre from the header ----
    def read_center(h):
        if center_override is not None:           # user supplied RA/DEC in the UI
            return SkyCoord(float(center_override[0]) * u.deg,
                            float(center_override[1]) * u.deg)
        if h.get("OBJCTRA") and h.get("OBJCTDEC"):
            return SkyCoord(str(h["OBJCTRA"]), str(h["OBJCTDEC"]), unit=(u.hourangle, u.deg))
        if h.get("RA") is not None and h.get("DEC") is not None:
            ra = str(h["RA"]); unit = u.hourangle if (":" in ra or " " in ra.strip()) else u.deg
            return SkyCoord(ra, str(h["DEC"]), unit=(unit, u.deg))
        if h.get("CRVAL1") is not None and h.get("CRVAL2") is not None:
            return SkyCoord(float(h["CRVAL1"]) * u.deg, float(h["CRVAL2"]) * u.deg)
        raise ValueError("No centre in header (need OBJCTRA/DEC, RA/DEC, or CRVAL1/2).")

    # ---- nested helper: pixel scale (arcsec/px) ----
    def read_scale(h):
        if pixel_scale:
            return float(pixel_scale)
        pix_um = float(h.get("XPIXSZ", 0.0)); fl_mm = float(h.get("FOCALLEN", 0.0))
        if pix_um > 0 and fl_mm > 0:
            return 206.265 * pix_um / fl_mm
        for key in ("PIXSCALE", "SECPIX", "SCALE"):
            if h.get(key):
                return float(h[key])
        raise ValueError("No pixel scale: set PIXEL_SCALE_ARCSEC, or add XPIXSZ+FOCALLEN "
                         "(or PIXSCALE) to the header.")

    # ---- nested helper: seed TAN WCS from centre + scale ----
    def make_wcs(center, scale, nx, ny, theta_deg=0.0, flip=False):
        s = scale / 3600.0; th = np.deg2rad(theta_deg); sx = -1.0 if flip else 1.0
        cd = np.array([[sx * s * np.cos(th), -s * np.sin(th)],
                       [sx * s * np.sin(th),  s * np.cos(th)]])
        w = WCS(naxis=2)
        w.wcs.crpix = [(nx + 1) / 2, (ny + 1) / 2]
        w.wcs.crval = [center.ra.deg, center.dec.deg]
        w.wcs.ctype = ["RA---TAN", "DEC--TAN"]; w.wcs.cd = cd
        return w

    # ---- nested helper: all pair length/angle vectors of a point set ----
    def pair_vecs(xy):
        i, j = np.triu_indices(len(xy), k=1); v = xy[j] - xy[i]
        return np.hypot(v[:, 0], v[:, 1]), np.arctan2(v[:, 1], v[:, 0])

    # === 1. read image + header meta (centre, scale, FOV, mid-exposure time) ===
    h = fits.getheader(fits_path); img = fits.getdata(fits_path).astype(float)
    while img.ndim > 2:
        img = img[0]
    ny, nx = img.shape
    scale = read_scale(h); center = read_center(h)
    t0 = Time(h["DATE-OBS"], format="isot", scale="utc") if h.get("DATE-OBS") else None
    tmid = (t0 + 0.5 * float(h.get("EXPTIME", 0.0)) * u.s) if t0 is not None else None
    m = dict(img=img, nx=nx, ny=ny, scale=scale, center=center,
             fov_deg=scale * max(nx, ny) / 3600.0, obj=h.get("OBJECT", "field"), tmid=tmid)

    stars = np.asarray(stars, float).reshape(-1, 3)
    if len(stars) < 3:
        print("    plate solve skipped: need 3+ stars"); return None, m

    x = stars[:, 0]; y = stars[:, 1]; flux = stars[:, 2]
    all_det = np.column_stack([x, y])
    if verbose:
        print(f"    OBJECT {m['obj']} | scale {scale:.4f} arcsec/px | "
              f"FOV {m['fov_deg']*60:.2f}' | {len(x)} stars in")

    # === 2. Gaia DR3 cone query around the header centre ===
    from astroquery.gaia import Gaia
    r = cfg["gaia_radius_factor"] * m["fov_deg"]
    q = (f"SELECT ra, dec, phot_g_mean_mag FROM gaiadr3.gaia_source "
         f"WHERE 1=CONTAINS(POINT('ICRS',ra,dec),"
         f"CIRCLE('ICRS',{center.ra.deg},{center.dec.deg},{r})) "
         f"AND phot_g_mean_mag < {cfg['gaia_maglimit']} ORDER BY phot_g_mean_mag")
    gtab = Gaia.launch_job_async(q).get_results()
    gaia = SkyCoord(np.array(gtab["ra"]) * u.deg, np.array(gtab["dec"]) * u.deg)
    gaia_xy = np.column_stack(make_wcs(center, scale, nx, ny).world_to_pixel(gaia))
    gsub = gaia[:cfg["n_match_gaia"]]; gsub_xy = gaia_xy[:cfg["n_match_gaia"]]

    # === 3. lock flip + rotation + shift from the brightest detected stars ===
    order = np.argsort(flux)[::-1]
    det = all_det[order[:cfg.get("n_det_match", 60)]]
    dL, dA = pair_vecs(det); best = None
    abin = np.deg2rad(cfg["rot_bin_deg"]); ltol = cfg["len_tol_px"]; tol = cfg["coarse_tol_px"]
    rel = cfg.get("len_rel_tol", 0.03)
    for flip in (False, True):
        C = gsub_xy * np.array([-1.0, 1.0]) if flip else gsub_xy
        cL, cA = pair_vecs(C); cord = np.argsort(cL); cLs = cL[cord]
        lo = np.searchsorted(cLs, dL * (1 - rel) - ltol)
        hi = np.searchsorted(cLs, dL * (1 + rel) + ltol)
        votes = []
        for p in range(len(dL)):
            qa = cA[cord[lo[p]:hi[p]]]
            votes.append(dA[p] - qa); votes.append(dA[p] - qa + np.pi)
        if not votes:
            continue
        votes = np.mod(np.concatenate(votes), 2 * np.pi)
        hist, edges = np.histogram(votes, bins=int(2 * np.pi / abin), range=(0, 2 * np.pi))
        for pk in np.argsort(hist)[-6:]:
            ang = edges[pk] + abin / 2
            R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
            RC = (R @ C.T).T
            shifts = (det[:, None, :] - RC[None, :, :]).reshape(-1, 2)
            key = np.round(shifts / tol).astype(int)
            uniq, cnt = np.unique(key, axis=0, return_counts=True)
            tsh = uniq[np.argmax(cnt)] * tol
            d, _ = cKDTree(RC + tsh).query(det, k=1)
            n = int((d < tol).sum())
            if best is None or n > best[0]:
                best = (n, flip, ang, tsh)
    if best is None or best[0] < 3:
        print("    plate solve: could not lock the field orientation against Gaia")
        return None, m
    _, flip, ang, tsh = best

    # === 4. match EVERY detected star to Gaia under the locked transform ===
    C = gsub_xy * np.array([-1.0, 1.0]) if flip else gsub_xy
    R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    d, j = cKDTree((R @ C.T).T + tsh).query(all_det, k=1)
    ok = d < cfg["coarse_tol_px"]
    if int(ok.sum()) < 3:
        print(f"    plate solve: only {int(ok.sum())} stars matched Gaia "
              "(raise gaia_maglimit or check the field)")
        return None, m

    # === 5. refine: fit WCS from matches, re-project with the FITTED scale, re-assign ===
    idx = np.where(ok)[0]; match = j[ok]
    for it in range(8):
        if len(idx) < 4:
            break
        wref = fit_wcs_from_points((all_det[idx, 0], all_det[idx, 1]),
                                   gsub[match], proj_point=center)
        ax, ay = wref.world_to_pixel(gsub)
        d, jj = cKDTree(np.column_stack([ax, ay])).query(all_det, k=1)
        rtol = max(2.0, 12.0 * (0.65 ** it))   # start wide, then tighten
        keep = d < rtol
        idx = np.where(keep)[0]; match = jj[keep]
        oo = np.argsort(d[idx]); idx = idx[oo]; match = match[oo]
        _, uq = np.unique(match, return_index=True)
        idx = idx[uq]; match = match[uq]
    nmatched = len(idx)
    if nmatched < 3:
        print("    plate solve: refinement lost the matches"); return None, m
    gaia_of = dict(zip(idx.tolist(), match.tolist()))

    # === 6. final WCS from ALL cleanly-matched stars ===
    # Using every refined match (rather than only the few brightest) gives the
    # fit wider spatial coverage across the frame and averages out individual
    # centroid noise, so the WCS stays accurate out to the corners.
    # (Order is irrelevant here — the least-squares fit is order-independent.)
    pts = all_det[idx]; matched = gsub[[gaia_of[k] for k in idx]]
    if len(pts) < 3:
        print("    plate solve: fewer than 3 matched stars"); return None, m
    w = fit_wcs_from_points((pts[:, 0], pts[:, 1]), matched, proj_point=center)

    # === 7. validate + geometry sanity check (NOT part of the fit) ===
    axv, ayv = w.world_to_pixel(gaia)
    dval, _ = cKDTree(np.column_stack([axv, ayv])).query(all_det, k=1)
    nval = int((dval < 2.0).sum())
    A = 0.0
    for a, b, c in combinations(range(len(pts)), 3):
        e1 = pts[b] - pts[a]; e2 = pts[c] - pts[a]
        # 2-D cross product (z-component); np.cross no longer accepts 2-D in numpy 2.0
        cross_z = float(e1[0] * e2[1] - e1[1] * e2[0])
        A = max(A, 0.5 * abs(cross_z))
    frac = A / (nx * ny)
    spread = np.hypot(pts[:, 0].std(), pts[:, 1].std()) / max(nx, ny)
    if verbose:
        print(f"  ✔  plate solve: matched {nmatched} stars to Gaia (flip={flip}, "
              f"rot={np.rad2deg(ang):.2f}°); WCS fit from all {len(pts)} matches")
        print(f"     validation: {nval}/{len(all_det)} stars land on Gaia (<2 px) | "
              f"hull {frac*100:.1f}% of frame, spread {spread:.2f}")
        if frac < 0.02 or spread < 0.12:
            print("     ⚠  stars are clustered/near-collinear → corners poorly constrained.")
    return w, m


def pixel_to_sky(x: float, y: float, wcs: WCS):
    """Convert pixel (x, y) to RA, DEC in degrees. (None, None) on error."""
    if wcs is None:
        return None, None
    try:
        sky = wcs.pixel_to_world(x, y)
        return float(sky.ra.deg), float(sky.dec.deg)
    except Exception:
        return None, None


_SIMBAD = Simbad()

try:
    _SIMBAD.add_votable_fields("otype")
except Exception as exc:
    print(f"(note) could not add SIMBAD 'otype' field: {exc}")

_VIZIER_BULK = Vizier(columns=["Source", "RA_ICRS", "DE_ICRS", "Gmag"],
                      row_limit=-1)

GAIA_CAT = "I/355/gaiadr3"

def _pick_col(colnames, *candidates):
    """First matching column name, case-insensitively."""
    lookup = {c.lower(): c for c in colnames}
    for cand in candidates:
        if cand.lower() in lookup:
            return lookup[cand.lower()]
    return None

def query_gaia_field(center, radius):
    """One bulk Gaia DR3 cone search over the whole field. Returns a Table | None."""
    try:
        cats = _VIZIER_BULK.query_region(center, radius=radius, catalog=GAIA_CAT)
        if cats and len(cats) > 0 and len(cats[0]) > 0:
            return cats[0]
    except Exception as exc:
        print(f"  Gaia bulk query failed: {exc}")
    return None

def query_simbad(ra, dec, radius_arcsec=30.0):
    """Single SIMBAD cone search. Returns a dict like the catalogs entries."""
    coord = SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame="icrs")
    try:
        tbl = _SIMBAD.query_region(coord, radius=radius_arcsec*u.arcsec)
        if tbl is not None and len(tbl) > 0:
            id_col = _pick_col(tbl.colnames, "main_id", "MAIN_ID")
            ot_col = _pick_col(tbl.colnames, "otype", "OTYPE")
            return {"found": True, "count": len(tbl),
                    "ids":   [str(r[id_col]) for r in tbl[:3]] if id_col else [],
                    "types": [str(r[ot_col]) for r in tbl[:3]] if ot_col else []}
        return {"found": False}
    except Exception as exc:
        return {"found": False, "error": str(exc)}

_VIZIER_PS1 = Vizier(columns=["objID", "RAJ2000", "DEJ2000", "rmag"],
                     row_limit=-1)

PS1_CAT = "II/349/ps1"

def query_panstarrs_field(center, radius):

    try:
        cats = _VIZIER_PS1.query_region(center, radius=radius, catalog=PS1_CAT)
        if cats and len(cats) > 0 and len(cats[0]) > 0:
            return cats[0]
    except Exception as exc:
        print(f"  Pan-STARRS query failed: {exc}")
    return None

def query_ned_field(center, radius):
    try:
        from astroquery.ipac.ned import Ned
        tbl = Ned.query_region(center, radius=radius)
        if tbl is not None and len(tbl) > 0:
            return tbl
    except Exception as exc:
        print(f"  NED query failed: {exc}")
    return None

def query_skybot_field(center, radius, epoch):
    if epoch is None:
        return None
    try:
        from astroquery.imcce import Skybot
        tbl = Skybot.cone_search(center, radius, epoch)
        if tbl is not None and len(tbl) > 0:
            return tbl
    except RuntimeError:
        # SkyBoT raises when no body is in the field - normal, not an error
        return None
    except Exception as exc:
        print(f"  SkyBoT query note: {exc}")
    return None

def _col_deg(tbl, col):
    """Return a column as a plain float array in degrees (handles Quantity cols)."""
    v = tbl[col]
    try:
        return u.Quantity(v).to(u.deg).value
    except Exception:
        return np.asarray(v, dtype=float)

def match_to_table(src_coords, tbl, ra_cands, de_cands, id_cands, radius_arcsec):
    """Vectorised nearest-neighbour match of src_coords against a catalog table.
    Returns (matched_bool_array, id_list).  Both length = len(src_coords)."""
    n = len(np.atleast_1d(src_coords))
    matched = np.zeros(n, dtype=bool)
    ids = [None] * n
    if tbl is None or len(tbl) == 0:
        return matched, ids
    ra_col = _pick_col(tbl.colnames, *ra_cands)
    de_col = _pick_col(tbl.colnames, *de_cands)
    id_col = _pick_col(tbl.colnames, *id_cands)
    if ra_col is None or de_col is None:
        return matched, ids
    cat = SkyCoord(ra=_col_deg(tbl, ra_col)*u.deg, dec=_col_deg(tbl, de_col)*u.deg)
    idx, sep2d, _ = src_coords.match_to_catalog_sky(cat)
    idx = np.atleast_1d(idx); sep2d = np.atleast_1d(sep2d)
    within = sep2d < radius_arcsec*u.arcsec
    for i in range(n):
        if within[i]:
            matched[i] = True
            if id_col is not None:
                ids[i] = str(tbl[id_col][int(idx[i])])
    return matched, ids


def cross_match(dao_sources, wcs, search_radius=30.0, max_objects=300,
                use_gaia=True, use_simbad=True, use_panstarrs=True, use_ned=True,
                use_skybot=True, epoch=None):
    """Bulk multi-catalog cross-match -> split known / new.

    Each catalog is ONE field query; matching is done locally (vectorised).
    Every source gets obj['matched_by'] = the catalog that confirmed it
    (Gaia_DR3 / PanSTARRS / NED / SkyBoT / SIMBAD), or None if it is new.
    """
    print(f'Cross-matching  radius={search_radius}"  max={max_objects}  '
          f"simbad={use_simbad} ps1={use_panstarrs} ned={use_ned} "
          f"skybot={use_skybot and epoch is not None}")

    objects = []
    if dao_sources is not None:
        for r in dao_sources:
            objects.append({"x": float(r["xcentroid"]),
                            "y": float(r["ycentroid"]),
                            "flux": float(r["peak"]), "origin": "DAO"})
    print(f"  Sources: {len(objects)}")

    if wcs is None:
        print("  \u26a0  No WCS - skipping catalog queries.")
        return [], objects

    batch = objects[:max_objects]
    if not batch:
        return [], []

    # 1) sky coords for every source
    ras, decs = [], []
    for obj in batch:
        ra, dec = pixel_to_sky(obj["x"], obj["y"], wcs)
        obj["ra"], obj["dec"] = ra, dec
        ras.append(ra); decs.append(dec)
    ras = np.array(ras); decs = np.array(decs)
    src_coords = SkyCoord(ra=ras*u.deg, dec=decs*u.deg)

    # 2) field centre + radius (covers all sources, with margin)
    center = SkyCoord(ra=np.median(ras)*u.deg, dec=np.median(decs)*u.deg)
    field_radius = src_coords.separation(center).max() + 2*search_radius*u.arcsec
    print(f"  Field  centre=({center.ra.deg:.4f}, {center.dec.deg:+.4f})  "
          f"r={field_radius.to(u.arcmin):.2f}")

    # 3) ONE bulk query per catalog
    def _bulk(name, fn, *a):
        t = time.time(); tbl = fn(*a)
        nrows = len(tbl) if tbl is not None else 0
        print(f"  {name:10s}: {nrows:5d} rows  ({time.time()-t:.1f}s)")
        return tbl

    gaia = _bulk("Gaia DR3",  query_gaia_field, center, field_radius) if use_gaia else None
    ps1  = _bulk("Pan-STARRS", query_panstarrs_field, center, field_radius) if use_panstarrs else None
    ned  = _bulk("NED",       query_ned_field, center, field_radius) if use_ned else None
    sbot = _bulk("SkyBoT",    query_skybot_field, center, field_radius, epoch) if (use_skybot and epoch is not None) else None

    # 4) vectorised matches against each downloaded catalog
    m_gaia, id_gaia = match_to_table(src_coords, gaia,
        ["RA_ICRS","ra","RAJ2000"], ["DE_ICRS","dec","DEJ2000"], ["Source","source"], search_radius)
    m_ps1,  id_ps1  = match_to_table(src_coords, ps1,
        ["RAJ2000","RA_ICRS","ra"], ["DEJ2000","DE_ICRS","dec"], ["objID","Source"], search_radius)
    m_ned,  id_ned  = match_to_table(src_coords, ned,
        ["RA","ra"], ["DEC","dec"], ["Object Name","Object_Name","Name"], search_radius)
    m_sbot, id_sbot = match_to_table(src_coords, sbot,
        ["RA","ra"], ["DEC","dec"], ["Name","Number"], search_radius)

    # 5) classify with a cascade; SIMBAD per-source only if still unmatched
    known, new = [], []
    counts = {"Gaia_DR3": 0, "PanSTARRS": 0, "NED": 0, "SkyBoT": 0, "SIMBAD": 0}
    n_simbad = 0
    for i, obj in enumerate(batch):
        cats = {
            "Gaia_DR3":  {"found": bool(m_gaia[i]), "ids": [id_gaia[i]] if id_gaia[i] else []},
            "PanSTARRS": {"found": bool(m_ps1[i]),  "ids": [id_ps1[i]]  if id_ps1[i]  else []},
            "NED":       {"found": bool(m_ned[i]),  "ids": [id_ned[i]]  if id_ned[i]  else []},
            "SkyBoT":    {"found": bool(m_sbot[i]), "ids": [id_sbot[i]] if id_sbot[i] else []},
            "SIMBAD":    {"found": False},
        }
        matched_by = None
        for name, mm in (("Gaia_DR3", m_gaia[i]), ("PanSTARRS", m_ps1[i]),
                         ("NED", m_ned[i]), ("SkyBoT", m_sbot[i])):
            if mm:
                matched_by = name; break
        if matched_by is None and use_simbad:
            s = query_simbad(obj["ra"], obj["dec"], search_radius); n_simbad += 1
            cats["SIMBAD"] = s
            if s.get("found"):
                matched_by = "SIMBAD"
        obj["catalogs"] = cats
        obj["matched_by"] = matched_by        # which catalog confirmed it (None = new)
        if matched_by:
            counts[matched_by] += 1
            known.append(obj)
        else:
            new.append(obj)

    breakdown = "  ".join(f"{k}={v}" for k, v in counts.items() if v)
    print(f"  SIMBAD per-source queries: {n_simbad}")
    print(f"  Matched by -> {breakdown if breakdown else '(none)'}")
    print(f"  -> Catalog matches: {len(known)}   \u2605 New: {len(new)}")
    return known, new


# ═══════════════════════════════════════════════════════════════════════════
#  DRIVER — one call the web API uses. Wraps the exact notebook steps.
# ═══════════════════════════════════════════════════════════════════════════
def _annotate_png(data, dao_sources, known, new, out_png):
    norm = ImageNormalize(data, interval=ZScaleInterval())
    fig, ax = plt.subplots(figsize=(9, 9), facecolor="black")
    ax.imshow(data, cmap="gray", origin="lower", norm=norm)
    for o in known:
        ax.scatter(o["x"], o["y"], s=60, facecolors="none",
                   edgecolors=C_KNOWN, linewidths=1.2)
    for o in new:
        ax.scatter(o["x"], o["y"], s=150, marker="*",
                   c=C_NEW, edgecolors="#8B0000", linewidths=1.2)
    ax.set_title(f"Known {len(known)}   New {len(new)}", color="white")
    ax.axis("off"); fig.tight_layout()
    fig.savefig(out_png, dpi=120, bbox_inches="tight", facecolor="black")
    plt.close(fig)


def detect_tetra3(image_raw, sub, sigma=5.0, min_area=5, max_area=200,
                  max_axis_ratio=2.0):
    """Detect sources with tetra3's centroider (local background subtraction +
    connected-component blobs). Complements DAOStarFinder: it handles uneven
    backgrounds and rejects single-pixel noise / trails differently.

    Returns a Table with the same schema as detect_sources
    (xcentroid / ycentroid / peak), or None if tetra3 isn't installed.
    """
    try:
        import tetra3
    except Exception:
        print("tetra3 not installed — skipping (pip install "
              "\"git+https://github.com/esa/tetra3.git\")")
        return None
    try:
        cents = tetra3.get_centroids_from_image(
            image_raw, sigma=sigma, min_area=min_area, max_area=max_area,
            max_axis_ratio=max_axis_ratio)
    except Exception as exc:
        print("tetra3 detection failed:", exc)
        return None

    cents = np.atleast_2d(np.asarray(cents, dtype=float))
    if cents.size == 0:
        return None
    ys, xs = cents[:, 0], cents[:, 1]          # tetra3 returns (row=y, col=x)

    h, w = sub.shape
    peaks = []
    for x, y in zip(xs, ys):
        y0, y1 = max(0, int(y) - 3), min(h, int(y) + 4)
        x0, x1 = max(0, int(x) - 3), min(w, int(x) + 4)
        box = sub[y0:y1, x0:x1]
        peaks.append(float(np.nanmax(box)) if box.size else 0.0)

    print(f"  tetra3 detected: {len(xs)}")
    return Table({"xcentroid": xs, "ycentroid": ys, "peak": np.array(peaks)})


def merge_detections(tbl_a, tbl_b, tol_px=3.0):
    """Union of two source tables, dropping duplicates: any source in tbl_b
    within tol_px of one already in tbl_a is treated as the same star and
    skipped. Returns one combined Table."""
    from astropy.table import vstack
    if tbl_a is None or len(tbl_a) == 0:
        return tbl_b
    if tbl_b is None or len(tbl_b) == 0:
        return tbl_a
    axy = np.column_stack([np.asarray(tbl_a["xcentroid"], float),
                           np.asarray(tbl_a["ycentroid"], float)])
    bxy = np.column_stack([np.asarray(tbl_b["xcentroid"], float),
                           np.asarray(tbl_b["ycentroid"], float)])
    d, _ = cKDTree(axy).query(bxy, k=1)
    keep = np.asarray(d) > tol_px               # only sources A didn't already have
    n_dup = int((~keep).sum())
    if not keep.any():
        print(f"  merge: +0 new (all {n_dup} overlapped)")
        return tbl_a
    add = tbl_b[keep]
    merged = vstack([tbl_a[["xcentroid", "ycentroid", "peak"]],
                     add[["xcentroid", "ycentroid", "peak"]]], join_type="exact")
    print(f"  merge: {len(tbl_a)} + {len(add)} new "
          f"({n_dup} overlapped) = {len(merged)}")
    return merged


def solve_astrometry_net(dao, fits_path, api_key=None, scale_hint=None,
                         solve_timeout=90, tries=2, wait=5):
    """Blind plate solve via astrometry.net (used when there is NO known centre).
    Needs an API key (free from nova.astrometry.net) and internet. Returns a WCS
    or None. Sends only the detected source list — no image upload.

    Retries on transient drops (the public server often closes the connection
    mid-solve when its queue is busy); the job usually succeeds on a later try.
    """
    if not api_key:
        print("astrometry.net: no API key given — skipping blind solve.")
        return None
    try:
        from astroquery.astrometry_net import AstrometryNet
        from astropy.io import fits as _fits
        ast = AstrometryNet(); ast.api_key = api_key
        ast.TIMEOUT = solve_timeout        # network timeout (separate from solve)
        with _fits.open(fits_path) as hdul:
            hdu = next((h for h in hdul if getattr(h, "data", None) is not None), hdul[0])
            h, w = hdu.data.shape
        xs = np.asarray(dao["xcentroid"], float)
        ys = np.asarray(dao["ycentroid"], float)
        order = np.argsort(np.asarray(dao["peak"], float))[::-1]
        settings = {}
        if scale_hint:
            settings.update(scale_units="arcsecperpix", scale_type="ev",
                            scale_est=float(scale_hint), scale_err=20.0)

        import time as _time
        for attempt in range(1, tries + 1):
            try:
                hdr = ast.solve_from_source_list(
                    xs[order].tolist(), ys[order].tolist(), int(w), int(h),
                    solve_timeout=solve_timeout, **settings)
                if hdr:
                    return WCS(hdr)
                print(f"astrometry.net: no solution (attempt {attempt}/{tries}).")
            except Exception as exc:
                print(f"astrometry.net attempt {attempt}/{tries} failed: {exc}")
            if attempt < tries:
                print(f"  retrying in {wait}s …")
                _time.sleep(wait)
        return None
    except Exception as exc:
        print("astrometry.net solve error:", exc)
        return None


def make_base_png(sub):
    """Clean grayscale PNG of the frame (no markers) at NATIVE resolution, for
    the interactive overlay. Returns (base64_png, width, height). Pixel coords
    of detections line up directly with this image (top-left origin)."""
    from PIL import Image
    import io as _io, base64 as _b64
    vmin, vmax = ZScaleInterval().get_limits(sub)
    scaled = np.clip((sub - vmin) / max(vmax - vmin, 1e-6), 0, 1)
    img8 = (scaled * 255).astype(np.uint8)
    h, w = img8.shape
    buf = _io.BytesIO()
    Image.fromarray(img8, mode="L").save(buf, format="PNG")
    return _b64.b64encode(buf.getvalue()).decode("ascii"), int(w), int(h)


def header_center_source(h):
    """Which header key provides the field centre, in priority order, or None.
    Mirrors plate_solve's own centre-reading logic so the branch matches it."""
    if h.get("OBJCTRA") and h.get("OBJCTDEC"):
        return "OBJCTRA/OBJCTDEC"
    if h.get("RA") is not None and h.get("DEC") is not None:
        return "RA/DEC"
    if h.get("CRVAL1") is not None and h.get("CRVAL2") is not None:
        return "CRVAL1/CRVAL2"
    return None


def run_pipeline(fits_path, out_png,
                 fwhm=3.0, auto_fwhm=True, threshold_sigma=5.0,
                 search_radius=30.0, max_objects=300,
                 sharp_lo=0.1, sharp_hi=2.0, round_lo=-1.0, round_hi=1.0,
                 detect_saturated_pass=True, sat_frac=0.6, sat_min_pixels=6,
                 sat_max_axis=2.0, use_gaia=True, use_simbad=True, use_panstarrs=True,
                 use_ned=True, use_skybot=True,
                 solver="auto", api_key=None, scale_hint=None,
                 use_dao=True, use_tetra3=False,
                 tetra_sigma=5.0, tetra_min_area=5, tetra_max_area=200,
                 tetra_max_axis=2.0, merge_tol_px=3.0):
    """Run the full pipeline on one FITS file. Returns a results dict and
    writes the annotated image to out_png."""
    data, header, wcs = load_fits(fits_path)
    sub, rms = preprocess(data)

    fwhm_used = estimate_fwhm(sub, rms, guess_fwhm=fwhm) if auto_fwhm else fwhm

    # ── Detection: DAOStarFinder and/or tetra3, merged into ONE list ──────
    dao = None
    if use_dao:
        dao = detect_sources(sub, rms, fwhm=fwhm_used, n_sigma=threshold_sigma,
                             sharplo=sharp_lo, sharphi=sharp_hi,
                             roundlo=round_lo, roundhi=round_hi)
        if detect_saturated_pass:
            sat = detect_saturated(sub, rms, sat_frac=sat_frac,
                                   min_pixels=sat_min_pixels,
                                   max_axis_ratio=sat_max_axis, existing=dao)
            if sat is not None and len(sat) > 0:
                dao = merge_detections(dao, sat, tol_px=merge_tol_px)

    if use_tetra3:
        t3 = detect_tetra3(data, sub, sigma=tetra_sigma,
                           min_area=tetra_min_area, max_area=tetra_max_area,
                           max_axis_ratio=tetra_max_axis)
        dao = merge_detections(dao, t3, tol_px=merge_tol_px) if dao is not None else t3

    n_detected = len(dao) if dao is not None else 0
    print(f"  Total sources (merged): {n_detected}")

    # ── Plate-solving branch ─────────────────────────────────────────────
    #   solver="auto"       : header has centre → Gaia; else → astrometry.net
    #   solver="gaia"       : force Gaia offline solve (uses header centre)
    #   solver="astrometry" : force astrometry.net blind solve
    # In "auto", if Gaia fails and an API key is present, fall back to astrometry.
    solver = (solver or "auto").lower()
    solver_used = "file" if wcs is not None else "none"
    center_source = None
    if wcs is None and dao is not None and len(dao) >= 3:
        stars = np.column_stack([np.asarray(dao["xcentroid"], float),
                                 np.asarray(dao["ycentroid"], float),
                                 np.asarray(dao["peak"], float)])
        center_source = header_center_source(header)

        def _try_gaia():
            try:
                w, _m = plate_solve(stars, fits_path, verbose=False)
                return w, "gaia_offline"
            except Exception as exc:
                print("Gaia offline solve failed:", exc)
                return None, "failed"

        def _try_astrometry():
            w = solve_astrometry_net(dao, fits_path, api_key=api_key, scale_hint=scale_hint)
            return w, ("astrometry_net" if w is not None else "failed")

        if solver == "astrometry":
            wcs, solver_used = _try_astrometry()
        elif solver == "gaia":
            wcs, solver_used = _try_gaia()
        else:  # auto
            if center_source is not None:
                wcs, solver_used = _try_gaia()
                if wcs is None and api_key:          # fall back to astrometry.net
                    print("Gaia failed — falling back to astrometry.net.")
                    wcs, solver_used = _try_astrometry()
            else:
                wcs, solver_used = _try_astrometry()

    epoch = None
    try:
        if header is not None and "DATE-OBS" in header:
            epoch = Time(header["DATE-OBS"])
    except Exception:
        epoch = None

    known, new = cross_match(dao, wcs, search_radius=search_radius,
                             max_objects=max_objects, use_gaia=use_gaia,
                             use_simbad=use_simbad,
                             use_panstarrs=use_panstarrs, use_ned=use_ned,
                             use_skybot=use_skybot, epoch=epoch)

    _annotate_png(data, dao, known, new, out_png)

    def _row(o, status):
        return {"x": round(float(o["x"]), 2), "y": round(float(o["y"]), 2),
                "ra": (round(float(o["ra"]), 6) if o.get("ra") is not None else None),
                "dec": (round(float(o["dec"]), 6) if o.get("dec") is not None else None),
                "flux": (round(float(o["flux"]), 1) if o.get("flux") is not None else None),
                "status": status, "matched_by": o.get("matched_by")}

    objects = [_row(o, "known") for o in known] + [_row(o, "new") for o in new]

    base_png, img_w, img_h = make_base_png(sub)   # clean image for the overlay

    # Telemetry: object name, pixel scale (arcsec/px), field of view (arcmin)
    object_name = header.get("OBJECT") if header is not None else None
    pixel_scale = None
    fov_arcmin = None
    try:
        if wcs is not None:
            from astropy.wcs.utils import proj_plane_pixel_scales
            sc = proj_plane_pixel_scales(wcs) * 3600.0          # arcsec/px per axis
            pixel_scale = float(np.mean(sc))
        elif header is not None and header.get("XPIXSZ") and header.get("FOCALLEN"):
            binning = float(header.get("XBINNING", 1) or 1)
            pixel_scale = 206.265 * float(header["XPIXSZ"]) * binning / float(header["FOCALLEN"])
        if pixel_scale:
            fov_arcmin = pixel_scale * max(img_w, img_h) / 60.0
    except Exception as exc:
        print("telemetry scale/FOV calc skipped:", exc)

    return {"n_sources": (len(dao) if dao is not None else 0),
            "n_known": len(known), "n_new": len(new),
            "fwhm_used": round(float(fwhm_used), 2),
            "wcs_ok": wcs is not None, "solver_used": solver_used,
            "center_source": center_source,
            "object_name": object_name,
            "pixel_scale": (round(pixel_scale, 4) if pixel_scale else None),
            "fov_arcmin": (round(fov_arcmin, 2) if fov_arcmin else None),
            "objects": objects,
            "base_image_png": base_png, "img_width": img_w, "img_height": img_h}

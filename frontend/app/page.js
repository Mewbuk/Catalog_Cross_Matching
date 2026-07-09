"use client";

import { useState, useRef } from "react";
import ResultsTable from "@/components/ResultsTable";
import InteractiveImage from "@/components/InteractiveImage";

const API = process.env.NEXT_PUBLIC_API_URL || "/api";

function Slider({ label, hint, value, onChange, min, max, step }) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <label className="text-sm text-ink">{label}</label>
        <span className="font-mono text-sm text-cyan">{value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(parseFloat(e.target.value))}
             className="w-full accent-cyan" />
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div className="rounded-xl border border-line bg-panel px-5 py-4">
      <div className={`font-mono text-3xl ${color}`}>{value}</div>
      <div className="mt-1 text-xs uppercase tracking-wider text-muted">{label}</div>
    </div>
  );
}

// Build a CSV string from the object list (client-side download).
function toCSV(objects) {
  const head = ["status", "matched_by", "x_pix", "y_pix", "ra_deg", "dec_deg", "flux"];
  const rows = objects.map((o) => [
    o.status, o.matched_by ?? "", o.x, o.y,
    o.ra ?? "", o.dec ?? "", o.flux ?? "",
  ].join(","));
  return [head.join(","), ...rows].join("\n");
}

function download(filename, dataUrl) {
  const a = document.createElement("a");
  a.href = dataUrl; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
}

export default function Home() {
  const [file, setFile] = useState(null);
  const [fwhm, setFwhm] = useState(3.0);
  const [threshold, setThreshold] = useState(5.0);
  const [radius, setRadius] = useState(30.0);
  const [autoFwhm, setAutoFwhm] = useState(true);

  // plate solving
  const [solver, setSolver] = useState("gaia");   // gaia (M-solving) | astrometry
  const [apiKey, setApiKey] = useState("");

  // catalogs to match against
  const [cats, setCats] = useState({
    gaia: true, simbad: true, panstarrs: true, ned: true, skybot: true,
  });
  const toggleCat = (k) => setCats((c) => ({ ...c, [k]: !c[k] }));

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [selected, setSelected] = useState(null);
  const inputRef = useRef(null);

  async function analyze() {
    setBusy(true); setError(null); setSelected(null);
    try {
      const fd = new FormData();
      if (file) fd.append("file", file);
      fd.append("fwhm", fwhm);
      fd.append("auto_fwhm", autoFwhm);
      fd.append("threshold_sigma", threshold);
      fd.append("search_radius", radius);
      fd.append("solver", solver);
      if (apiKey) fd.append("api_key", apiKey);
      fd.append("use_gaia", cats.gaia);
      fd.append("use_simbad", cats.simbad);
      fd.append("use_panstarrs", cats.panstarrs);
      fd.append("use_ned", cats.ned);
      fd.append("use_skybot", cats.skybot);
      const res = await fetch(`${API}/analyze`, { method: "POST", body: fd });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error || "Analysis failed.");
      setResult(json);
    } catch (e) {
      setError(e.message?.includes("fetch")
        ? `Can't reach the pipeline at ${API}. Is the backend running?`
        : e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="starfield relative mb-10 overflow-hidden rounded-2xl border border-line bg-panel/40 px-8 py-10">
        <p className="mb-2 font-mono text-xs uppercase tracking-[0.3em] text-cyan">
          FITS &middot; source detection &middot; catalog cross-match
        </p>
        <h1 className="text-4xl font-semibold leading-tight text-ink md:text-5xl">Astrometry Console</h1>
        <p className="mt-3 max-w-xl text-muted">
          Upload a FITS frame, detect optical sources, resolve their sky
          coordinates, and flag the ones that aren&apos;t catalogued yet.
        </p>
      </header>

      <div className="grid gap-8 md:grid-cols-[340px_1fr]">
        {/* Controls */}
        <section className="space-y-5">
          <div className="rounded-2xl border border-line bg-panel p-5">
            <h2 className="mb-4 text-sm font-medium uppercase tracking-wider text-muted">Input</h2>
            <button onClick={() => inputRef.current?.click()}
                    className="w-full rounded-xl border border-dashed border-line bg-panel2/50 px-4 py-6 text-center transition hover:border-cyan/50">
              <div className="text-sm text-ink">{file ? file.name : "Choose a FITS file"}</div>
              <div className="mt-1 text-xs text-muted">
                {file ? "Click to replace" : ".fits, .fit, .fts \u2014 or run the demo"}
              </div>
            </button>
            <input ref={inputRef} type="file" accept=".fits,.fit,.fts,.fz" hidden
                   onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </div>

          <div className="space-y-5 rounded-2xl border border-line bg-panel p-5">
            <h2 className="text-sm font-medium uppercase tracking-wider text-muted">Detection</h2>
            <label className="flex items-center justify-between">
              <span className="text-sm text-ink">Auto-measure FWHM</span>
              <input type="checkbox" checked={autoFwhm}
                     onChange={(e) => setAutoFwhm(e.target.checked)}
                     className="h-4 w-4 accent-cyan" />
            </label>
            <Slider label="FWHM (px)" value={fwhm} min={1} max={10} step={0.5} onChange={setFwhm}
                    hint={autoFwhm ? "Starting guess; measured per image" : "Fixed value"} />
            <Slider label="Threshold (σ)" value={threshold} min={1} max={15} step={0.5}
                    onChange={setThreshold} hint="Higher = stricter, fewer noise dots" />
            <Slider label="Match radius (arcsec)" value={radius} min={1} max={120} step={1}
                    onChange={setRadius} hint="How close a catalog star must be" />
          </div>

          {/* Plate solving — choose the solver */}
          <div className="space-y-3 rounded-2xl border border-line bg-panel p-5">
            <h2 className="text-sm font-medium uppercase tracking-wider text-muted">Plate solving</h2>
            <div className="grid grid-cols-2 gap-2">
              {[
                ["gaia", "M-solving"],
                ["astrometry", "Astrometry.net"],
              ].map(([val, label]) => (
                <button key={val} onClick={() => setSolver(val)}
                  className={`rounded-lg border px-2 py-2 text-xs transition ${
                    solver === val
                      ? "border-cyan/60 bg-cyan/10 text-cyan"
                      : "border-line text-muted hover:border-cyan/40"
                  }`}>
                  {label}
                </button>
              ))}
            </div>
            <p className="text-xs text-muted">
              {solver === "gaia" && "Offline M-solving using the header's center."}
              {solver === "astrometry" && "Blind astrometry.net solve (needs an API key)."}
            </p>
            {solver === "astrometry" && (
              <div>
                <label className="mb-1 block text-xs text-muted">astrometry.net API key</label>
                <input value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                       type="password" placeholder="from nova.astrometry.net"
                       className="w-full rounded-lg border border-line bg-panel2 px-3 py-2 font-mono text-sm text-ink outline-none focus:border-cyan/50" />
              </div>
            )}
            <p className="text-[11px] text-muted">Only runs when the file has no WCS of its own.</p>
          </div>

          {/* Catalogs to match against */}
          <div className="space-y-2 rounded-2xl border border-line bg-panel p-5">
            <h2 className="mb-1 text-sm font-medium uppercase tracking-wider text-muted">Catalogs</h2>
            {[
              ["gaia", "Gaia DR3", "stars"],
              ["panstarrs", "Pan-STARRS", "faint optical"],
              ["ned", "NED", "galaxies / quasars"],
              ["skybot", "SkyBoT", "asteroids (needs DATE-OBS)"],
              ["simbad", "SIMBAD", "named objects (fallback)"],
            ].map(([k, label, hint]) => (
              <label key={k} className="flex cursor-pointer items-center justify-between rounded-lg px-1 py-1.5 hover:bg-panel2/50">
                <span className="text-sm text-ink">{label}
                  <span className="ml-2 text-xs text-muted">{hint}</span>
                </span>
                <input type="checkbox" checked={cats[k]} onChange={() => toggleCat(k)}
                       className="h-4 w-4 accent-cyan" />
              </label>
            ))}
          </div>

          <button onClick={analyze} disabled={busy}
                  className={`w-full rounded-xl border border-cyan/50 bg-cyan/10 px-4 py-3 font-medium text-cyan transition hover:bg-cyan/20 disabled:opacity-60 ${busy ? "working" : ""}`}>
            {busy ? "Analyzing\u2026" : "Run detection"}
          </button>
          {error && (
            <p className="rounded-lg border border-newobj/40 bg-newobj/10 px-3 py-2 text-sm text-newobj">{error}</p>
          )}
        </section>

        {/* Results */}
        <section className="space-y-6">
          {!result && !busy && (
            <div className="flex h-full min-h-[400px] items-center justify-center rounded-2xl border border-dashed border-line text-muted">
              Results will appear here after you run detection.
            </div>
          )}
          {busy && (
            <div className="flex h-full min-h-[400px] flex-col items-center justify-center rounded-2xl border border-line bg-panel text-muted">
              <div className="mb-3 h-8 w-8 animate-spin rounded-full border-2 border-line border-t-cyan" />
              Detecting, solving, and cross-matching&hellip;
            </div>
          )}

          {result && !busy && (
            <>
              {result.demo && (
                <p className="rounded-lg border border-amber/40 bg-amber/10 px-3 py-2 text-sm text-amber">
                  Demo data (backend in DEMO_MODE or no file uploaded).
                </p>
              )}
              <div className="grid grid-cols-3 gap-4">
                <Stat label="Detected" value={result.counts.detected} color="text-cyan" />
                <Stat label="Known" value={result.counts.known} color="text-known" />
                <Stat label="New" value={result.counts.new} color="text-newobj" />
              </div>

              {/* interactive image + download buttons */}
              <div className="rounded-2xl border border-line bg-panel p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div className="font-mono text-xs text-muted">
                    FWHM {result.fwhm_used}px &middot; WCS {result.wcs_ok ? "solved" : "none"}
                    {result.solver_used && result.solver_used !== "file" && result.solver_used !== "demo" && (
                      <> &middot; {
                        result.solver_used === "gaia_offline" ? "Gaia solve" :
                        result.solver_used === "astrometry_net" ? "astrometry.net solve" :
                        result.solver_used === "failed" ? "solve failed" : result.solver_used
                      }{result.center_source ? ` (center from ${result.center_source})` : ""}</>
                    )}
                    {result.solver_used === "file" && <> &middot; WCS from file</>}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => download("detections.png", `data:image/png;base64,${result.image_png_base64}`)}
                      className="rounded-lg border border-line px-3 py-1.5 text-xs text-ink hover:border-cyan/50">
                      Download image
                    </button>
                    <button
                      onClick={() => download("objects.csv",
                        "data:text/csv;charset=utf-8," + encodeURIComponent(toCSV(result.objects)))}
                      className="rounded-lg border border-line px-3 py-1.5 text-xs text-ink hover:border-cyan/50">
                      Download CSV
                    </button>
                  </div>
                </div>
                {result.base_image_png ? (
                  <InteractiveImage
                    base64={result.base_image_png}
                    width={result.img_width} height={result.img_height}
                    objects={result.objects}
                    selected={selected} onSelect={setSelected}
                  />
                ) : (
                  <div className="p-8 text-center text-muted">No image returned.</div>
                )}
              </div>

              <ResultsTable objects={result.objects} selected={selected} onSelect={setSelected} />
            </>
          )}
        </section>
      </div>

      <footer className="mt-12 border-t border-line pt-6 font-mono text-xs text-muted">
        DAOStarFinder &middot; astrometry.net / Gaia &middot; SIMBAD / Pan-STARRS / NED / SkyBoT
      </footer>
    </main>
  );
}

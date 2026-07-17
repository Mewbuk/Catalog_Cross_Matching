"use client";

import { useState, useRef } from "react";
import ResultsTable from "@/components/ResultsTable";
import InteractiveImage from "@/components/InteractiveImage";

const API = process.env.NEXT_PUBLIC_API_URL || "/api";

function Slider({ label, hint, value, onChange, min, max, step }) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <label className="font-mono text-[0.8rem] text-ink">{label}</label>
        <span className="font-mono text-sm text-cyan">{value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(parseFloat(e.target.value))}
             className="w-full accent-cyan" />
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

function Panel({ title, children }) {
  return (
    <div className="rounded-xl border border-line bg-panel/70 p-5">
      <h2 className="mb-4 font-mono text-[0.7rem] uppercase tracking-[0.18em] text-muted">
        <span className="text-cyan">▸ </span>{title}
      </h2>
      {children}
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div className="rounded-lg border border-line bg-panel/70 px-4 py-4">
      <div className={`font-mono text-3xl font-bold tabular-nums ${color}`}>{value}</div>
      <div className="mt-1 font-mono text-[0.64rem] uppercase tracking-[0.14em] text-muted">{label}</div>
    </div>
  );
}

function Tele({ label, value }) {
  return (
    <span className="font-mono text-[0.72rem] text-muted">
      {label} <b className="font-medium text-ink">{value}</b>
    </span>
  );
}

function toCSV(objects) {
  const head = ["status", "matched_by", "x_pix", "y_pix", "ra_deg", "dec_deg", "flux"];
  const rows = objects.map((o) => [
    o.status, o.matched_by ?? "", o.x, o.y, o.ra ?? "", o.dec ?? "", o.flux ?? "",
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
  const [threshold, setThreshold] = useState(8.0);
  const [radius, setRadius] = useState(30.0);
  const [autoFwhm, setAutoFwhm] = useState(true);

  const [useDao, setUseDao] = useState(true);
  const [useTetra3, setUseTetra3] = useState(true);
  const [tetraSigma, setTetraSigma] = useState(5.0);

  const [solver, setSolver] = useState("gaia");
  const [apiKey, setApiKey] = useState("");

  const [cats, setCats] = useState({
    gaia: true, panstarrs: true, ned: true, skybot: true, simbad: false,
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
      fd.append("use_dao", useDao);
      fd.append("use_tetra3", useTetra3);
      fd.append("tetra_sigma", tetraSigma);
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

  const solverName = (s) =>
    s === "gaia_offline" ? "Gaia" : s === "astrometry_net" ? "Astrometry.net"
    : s === "file" ? "from file" : s === "demo" ? "demo" : s === "failed" ? "failed" : s;

  return (
    <main className="mx-auto max-w-6xl px-6 pb-14">
      {/* Editorial hero (C-style), tuned to the HUD blue palette */}
      <header className="px-2 pt-12 pb-8 text-center">
        <p className="mb-2 font-mono text-[0.7rem] uppercase tracking-[0.3em] text-cyan">
          FITS &middot; detection &middot; cross-match
        </p>
        <h1 className="font-serif text-5xl leading-[1.04] md:text-6xl">
          Catalog <em className="not-italic text-[#7dd3fc] italic">Matcher</em>
        </h1>
        <p className="mx-auto mt-3 max-w-xl leading-relaxed text-muted">
          Upload a frame. We detect every optical source, place it on the sky,
          and reveal what&apos;s known &mdash; and what isn&apos;t.
        </p>
      </header>

      <div className="grid gap-5 md:grid-cols-[300px_1fr]">
        {/* ---------- Controls ---------- */}
        <section className="space-y-4">
          <Panel title="Input">
            <button onClick={() => inputRef.current?.click()}
              className="w-full rounded-lg border border-dashed border-line bg-panel2/50 px-4 py-6 text-center transition hover:border-cyan/50">
              <div className="text-sm text-ink">{file ? file.name : "Choose a FITS file"}</div>
              <div className="mt-1 text-xs text-muted">
                {file ? "Click to replace" : ".fits, .fit, .fts \u2014 or run the demo"}
              </div>
            </button>
            <input ref={inputRef} type="file" accept=".fits,.fit,.fts,.fz" hidden
                   onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </Panel>

          <Panel title="Detectors">
            <label className="flex cursor-pointer items-center justify-between py-1.5">
              <span className="font-mono text-[0.8rem] text-ink">DAOStarFinder</span>
              <input type="checkbox" checked={useDao} onChange={(e) => setUseDao(e.target.checked)}
                     className="h-4 w-4 accent-cyan" />
            </label>
            {useDao && (
              <div className="mt-2 space-y-4 border-l border-line pl-3">
                <label className="flex items-center justify-between">
                  <span className="font-mono text-[0.78rem] text-muted">Auto-FWHM</span>
                  <input type="checkbox" checked={autoFwhm} onChange={(e) => setAutoFwhm(e.target.checked)}
                         className="h-4 w-4 accent-cyan" />
                </label>
                {!autoFwhm && (
                  <Slider label="FWHM (px)" value={fwhm} min={1} max={10} step={0.5} onChange={setFwhm} />
                )}
                <Slider label="Threshold (σ)" value={threshold} min={1} max={15} step={0.5}
                        onChange={setThreshold} hint="Higher = stricter" />
              </div>
            )}
            <label className="mt-3 flex cursor-pointer items-center justify-between py-1.5">
              <span className="font-mono text-[0.8rem] text-ink">tetra3</span>
              <input type="checkbox" checked={useTetra3} onChange={(e) => setUseTetra3(e.target.checked)}
                     className="h-4 w-4 accent-cyan" />
            </label>
            {useTetra3 && (
              <div className="mt-2 border-l border-line pl-3">
                <Slider label="tetra3 σ" value={tetraSigma} min={1} max={15} step={0.5} onChange={setTetraSigma} />
              </div>
            )}
            <p className="mt-3 text-xs text-muted">
              {useDao && useTetra3 ? "Both run; results merged (duplicates removed)."
                : useDao ? "DAOStarFinder only." : useTetra3 ? "tetra3 only." : "\u26a0 No detector selected."}
            </p>
          </Panel>

          <Panel title="Plate solving">
            <div className="grid grid-cols-2 gap-1.5">
              {[["gaia", "M-solving"], ["astrometry", "Astrometry.net"]].map(([v, l]) => (
                <button key={v} onClick={() => setSolver(v)}
                  className={`rounded-md border px-2 py-2 font-mono text-[0.74rem] transition ${
                    solver === v ? "border-cyan bg-cyan text-[#06121f] font-bold"
                                 : "border-line text-muted hover:border-cyan/50"}`}>
                  {l}
                </button>
              ))}
            </div>
            {solver === "astrometry" && (
              <div className="mt-3">
                <label className="mb-1 block text-xs text-muted">astrometry.net API key</label>
                <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} type="password"
                       placeholder="from nova.astrometry.net"
                       className="w-full rounded-md border border-line bg-panel2 px-3 py-2 font-mono text-sm text-ink outline-none focus:border-cyan/50" />
              </div>
            )}
            <p className="mt-2 text-xs text-muted">Runs only if the file has no WCS.</p>
          </Panel>

          <Panel title="Catalogs">
            {[["gaia", "Gaia DR3"], ["panstarrs", "Pan-STARRS"], ["ned", "NED"],
              ["skybot", "SkyBoT"], ["simbad", "SIMBAD"]].map(([k, label]) => (
              <label key={k} className="flex cursor-pointer items-center justify-between py-1.5">
                <span className="font-mono text-[0.8rem] text-ink">{label}</span>
                <input type="checkbox" checked={cats[k]} onChange={() => toggleCat(k)}
                       className="h-4 w-4 accent-cyan" />
              </label>
            ))}
            <div className="mt-3">
              <Slider label="Match radius (″)" value={radius} min={1} max={120} step={1} onChange={setRadius} />
            </div>
          </Panel>

          <button onClick={analyze} disabled={busy}
            className={`w-full rounded-md border border-cyan bg-cyan/15 px-4 py-3 font-mono text-[0.82rem] font-semibold uppercase tracking-[0.05em] text-cyan transition hover:bg-cyan/25 disabled:opacity-60 ${busy ? "working" : ""}`}>
            {busy ? "Analyzing\u2026" : "Run detection"}
          </button>
          {error && (
            <p className="rounded-md border border-newobj/40 bg-newobj/10 px-3 py-2 text-sm text-newobj">{error}</p>
          )}
        </section>

        {/* ---------- Results ---------- */}
        <section className="space-y-5">
          {!result && !busy && (
            <div className="flex h-full min-h-[420px] items-center justify-center rounded-xl border border-dashed border-line text-muted">
              Results appear here after you run detection.
            </div>
          )}
          {busy && (
            <div className="flex h-full min-h-[420px] flex-col items-center justify-center rounded-xl border border-line bg-panel/70 text-muted">
              <div className="mb-3 h-8 w-8 animate-spin rounded-full border-2 border-line border-t-cyan" />
              Detecting, solving, and cross-matching&hellip;
            </div>
          )}

          {result && !busy && (
            <>
              {result.demo && (
                <p className="rounded-md border border-amber/40 bg-amber/10 px-3 py-2 text-sm text-amber">
                  Demo data (backend in DEMO_MODE or no file uploaded).
                </p>
              )}

              <div className="grid grid-cols-3 gap-3">
                <Stat label="Detected" value={result.counts.detected} color="text-cyan" />
                <Stat label="Known" value={result.counts.known} color="text-known" />
                <Stat label="New" value={result.counts.new} color="text-newobj" />
              </div>

              <div className="space-y-5">
                {/* image block: telemetry bar sits ON TOP of the image, full width */}
                <div>
                  <div className="overflow-hidden rounded-xl border border-line">
                    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-line border-l-2 border-l-cyan bg-panel/95 px-4 py-2.5">
                      <Tele label="OBJECT" value={result.object_name || "\u2014"} />
                      <Tele label="SCALE" value={result.pixel_scale ? `${result.pixel_scale}\u2033/px` : "\u2014"} />
                      <Tele label="FOV" value={result.fov_arcmin ? `${result.fov_arcmin}\u2032` : "\u2014"} />
                      <Tele label="FWHM" value={`${result.fwhm_used}px`} />
                      <Tele label="SOLVER" value={solverName(result.solver_used)} />
                      <span className="ml-auto flex items-center gap-1.5 font-mono text-[0.72rem]">
                        {result.wcs_ok ? (
                          <><span className="dot-live" /><span className="text-known">WCS SOLVED</span></>
                        ) : (
                          <span className="text-newobj">NO WCS</span>
                        )}
                      </span>
                    </div>
                    {result.base_image_png ? (
                      <InteractiveImage
                        base64={result.base_image_png}
                        width={result.img_width} height={result.img_height}
                        objects={result.objects}
                        selected={selected} onSelect={setSelected}
                        reticle
                      />
                    ) : (
                      <div className="p-8 text-center text-muted">No image returned.</div>
                    )}
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <span className="font-mono text-[0.72rem] text-muted">
                      {result.center_source ? `center ${result.center_source}` : ""}
                    </span>
                    <div className="flex gap-2">
                      <button onClick={() => download("detections.png", `data:image/png;base64,${result.image_png_base64}`)}
                        className="rounded-md border border-line px-3 py-1.5 font-mono text-[0.72rem] text-ink hover:border-cyan/50">
                        Image
                      </button>
                      <button onClick={() => download("objects.csv",
                        "data:text/csv;charset=utf-8," + encodeURIComponent(toCSV(result.objects)))}
                        className="rounded-md border border-line px-3 py-1.5 font-mono text-[0.72rem] text-ink hover:border-cyan/50">
                        CSV
                      </button>
                    </div>
                  </div>
                </div>

                <ResultsTable objects={result.objects} selected={selected} onSelect={setSelected} />
              </div>
            </>
          )}
        </section>
      </div>

      <footer className="mt-12 border-t border-line pt-6 font-mono text-[0.72rem] text-muted">
        DAOStarFinder + tetra3 &middot; Gaia / astrometry.net &middot; Gaia DR3 / Pan-STARRS / NED / SkyBoT / SIMBAD
      </footer>
    </main>
  );
}

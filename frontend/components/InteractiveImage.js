"use client";

import { useRef, useState, useCallback, useEffect } from "react";

// Interactive detection viewer: a base image with an SVG marker overlay.
// - hover a marker  -> tooltip with RA/DEC/flux
// - click a marker  -> selects it (highlights here + in the table via onSelect)
// - wheel           -> zoom toward the cursor (page does NOT scroll)
// - drag            -> pan
// Markers use the object's pixel coords directly (image top-left origin).
export default function InteractiveImage({ base64, width, height, objects, selected, onSelect, reticle }) {
  const wrapRef = useRef(null);
  const [view, setView] = useState({ scale: 1, tx: 0, ty: 0 });
  const [hover, setHover] = useState(null);
  const dragging = useRef(null);

  // Wheel must be a NON-passive native listener, otherwise React ignores
  // preventDefault() and the whole page scrolls while zooming.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const handler = (e) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      setView((v) => {
        const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        const scale = Math.min(8, Math.max(1, v.scale * factor));
        const k = scale / v.scale;
        return { scale, tx: mx - k * (mx - v.tx), ty: my - k * (my - v.ty) };
      });
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  const onDown = (e) => {
    dragging.current = { x: e.clientX, y: e.clientY, moved: false, ...view };
  };
  const onMove = (e) => {
    const d = dragging.current;
    if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) d.moved = true;   // it's a pan
    setView((v) => ({ ...v, tx: d.tx + dx, ty: d.ty + dy }));
  };
  const onUp = () => { dragging.current = null; };
  const reset = () => setView({ scale: 1, tx: 0, ty: 0 });

  // Centre a source in the viewport and zoom in on it.
  // Screen position of an image pixel is  tx + scale * (px * s), where
  // s converts image pixels -> displayed pixels at scale 1. Solving for the
  // translation that puts the source at the viewport centre gives the below.
  const SELECT_ZOOM = 2.0;
  const focusOn = useCallback((o) => {
    const el = wrapRef.current;
    if (!el || !o) return;
    const s = el.clientWidth / width;
    const scale = SELECT_ZOOM;
    setView({
      scale,
      tx: el.clientWidth / 2 - scale * o.x * s,
      ty: el.clientHeight / 2 - scale * o.y * s,
    });
  }, [width]);

  // Selecting a source (from a marker click OR a table row) centres it here.
  useEffect(() => {
    if (selected == null) return;
    focusOn(objects?.[selected]);
  }, [selected, objects, focusOn]);

  // Only treat it as a marker click if the pointer didn't pan.
  const clickMarker = (i, sel) => {
    if (dragging.current?.moved) return;
    onSelect?.(sel ? null : i);
  };

  return (
    <div className="relative">
      <div
        ref={wrapRef}
        onMouseDown={onDown} onMouseMove={onMove}
        onMouseUp={onUp} onMouseLeave={onUp}
        className="relative aspect-square w-full cursor-grab overflow-hidden rounded-lg bg-space active:cursor-grabbing"
      >
        <div
          className="absolute left-0 top-0 origin-top-left"
          style={{ transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.scale})` }}
        >
          {/* base image */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt="Detection frame" src={`data:image/png;base64,${base64}`}
            className="block w-full select-none" draggable={false}
            style={{ width: wrapRef.current?.clientWidth || "100%" }}
          />
          {/* marker overlay in image pixel space */}
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="pointer-events-none absolute left-0 top-0 h-full w-full"
          >
            {objects.map((o, i) => {
              const sel = selected === i;
              const isNew = o.status === "new";
              const r = isNew ? 7 : 5;
              const color = isNew ? "#FB7185" : "#34D399";
              // Invisible hit target: at least ~10px in image space, and it
              // shrinks as you zoom in so it never overlaps neighbouring stars.
              const hitR = Math.max(r + 4, 10 / Math.max(view.scale, 1) + r);
              return (
                <g key={i}>
                  {/* clickable area: the whole disc, not just the stroke */}
                  <circle
                    cx={o.x} cy={o.y} r={hitR}
                    fill="transparent"
                    className="pointer-events-auto cursor-pointer"
                    onMouseEnter={() => setHover({ i, o })}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => clickMarker(i, sel)}
                  />
                  {/* the visible marker (not interactive — the hit disc handles it) */}
                  <circle
                    cx={o.x} cy={o.y} r={sel ? r + 4 : r}
                    fill="none" stroke={color}
                    strokeWidth={sel ? 2.5 : 1.5}
                    className="pointer-events-none"
                  />
                  {sel && (
                    <circle cx={o.x} cy={o.y} r={r + 9} fill="none"
                            stroke={color} strokeWidth={1} opacity={0.5}
                            className="pointer-events-none" />
                  )}
                </g>
              );
            })}
          </svg>
        </div>

        {/* subtle HUD reticle, fixed to the viewport (not the zoom layer) */}
        {reticle && (
          <svg viewBox="0 0 100 100" preserveAspectRatio="none"
               className="pointer-events-none absolute inset-0 h-full w-full">
            <line x1="50" y1="0" x2="50" y2="100" stroke="#38BDF8" strokeWidth="0.15" opacity="0.18" />
            <line x1="0" y1="50" x2="100" y2="50" stroke="#38BDF8" strokeWidth="0.15" opacity="0.18" />
            <circle cx="50" cy="50" r="12" fill="none" stroke="#38BDF8" strokeWidth="0.15" opacity="0.22" />
            <path d="M47 50h6M50 47v6" stroke="#38BDF8" strokeWidth="0.25" opacity="0.5" />
          </svg>
        )}

        {/* hover tooltip (screen-space, follows the marker's data) */}
        {hover && (
          <div className="pointer-events-none absolute left-3 top-3 rounded-lg border border-line bg-space/90 px-3 py-2 font-mono text-xs text-ink shadow-lg">
            <div className={hover.o.status === "new" ? "text-newobj" : "text-known"}>
              {hover.o.status === "new" ? "NEW" : hover.o.matched_by || "known"}
            </div>
            <div>RA {hover.o.ra != null ? hover.o.ra.toFixed(5) + "\u00b0" : "\u2014"}</div>
            <div>DEC {hover.o.dec != null ? (hover.o.dec >= 0 ? "+" : "") + hover.o.dec.toFixed(5) + "\u00b0" : "\u2014"}</div>
            <div className="text-muted">flux {hover.o.flux != null ? hover.o.flux.toFixed(0) : "\u2014"}</div>
          </div>
        )}
      </div>

      {/* controls */}
      <div className="mt-2 flex items-center justify-between font-mono text-xs text-muted">
        <span>scroll to zoom &middot; drag to pan &middot; click a marker</span>
        <button onClick={reset} className="rounded-md border border-line px-2 py-1 text-ink hover:border-cyan/50">
          Reset view ({view.scale.toFixed(1)}×)
        </button>
      </div>
    </div>
  );
}

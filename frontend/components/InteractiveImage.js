"use client";

import { useRef, useState, useCallback, useEffect } from "react";

// Interactive detection viewer: a base image with an SVG marker overlay.
// - hover a marker  -> tooltip with RA/DEC/flux
// - click a marker  -> selects it (highlights here + in the table via onSelect)
// - wheel           -> zoom toward the cursor (page does NOT scroll)
// - drag            -> pan
// Markers use the object's pixel coords directly (image top-left origin).
export default function InteractiveImage({ base64, width, height, objects, selected, onSelect }) {
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

  const onDown = (e) => { dragging.current = { x: e.clientX, y: e.clientY, ...view }; };
  const onMove = (e) => {
    const d = dragging.current;
    if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    setView((v) => ({ ...v, tx: d.tx + dx, ty: d.ty + dy }));
  };
  const onUp = () => { dragging.current = null; };
  const reset = () => setView({ scale: 1, tx: 0, ty: 0 });

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
              return (
                <g key={i}>
                  <circle
                    cx={o.x} cy={o.y} r={sel ? r + 4 : r}
                    fill="none" stroke={color}
                    strokeWidth={sel ? 2.5 : 1.5}
                    className="pointer-events-auto cursor-pointer"
                    onMouseEnter={() => setHover({ i, o })}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => onSelect?.(sel ? null : i)}
                  />
                  {sel && (
                    <circle cx={o.x} cy={o.y} r={r + 9} fill="none"
                            stroke={color} strokeWidth={1} opacity={0.5} />
                  )}
                </g>
              );
            })}
          </svg>
        </div>

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

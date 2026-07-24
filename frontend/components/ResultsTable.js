"use client";

import { useEffect, useRef } from "react";

// Object list. Rows are selectable and stay in sync with the image markers:
// clicking a row selects it (and the marker); selecting a marker scrolls the
// matching row into view and highlights it.
export default function ResultsTable({ objects, selected, onSelect }) {
  const rowRefs = useRef({});
  const scrollRef = useRef(null);

  // Keep the selected row visible, but scroll ONLY inside this container —
  // scrollIntoView() would scroll the whole page, which is jarring when the
  // selection came from clicking a marker on the image.
  useEffect(() => {
    const box = scrollRef.current;
    const row = selected != null ? rowRefs.current[selected] : null;
    if (!box || !row) return;
    const b = box.getBoundingClientRect();
    const r = row.getBoundingClientRect();
    const delta = (r.top - b.top) - (box.clientHeight / 2 - r.height / 2);
    box.scrollTo({ top: box.scrollTop + delta, behavior: "smooth" });
  }, [selected]);

  if (!objects?.length) return null;

  const badge = (o) =>
    o.status === "known"
      ? { label: o.matched_by || "known", cls: "text-known border-known/40 bg-known/10" }
      : { label: "new", cls: "text-newobj border-newobj/40 bg-newobj/10" };

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-panel">
      <div ref={scrollRef} className="max-h-[460px] overflow-auto">
        <table className="w-full border-collapse text-left text-sm">
          <thead className="sticky top-0 bg-panel2 text-muted">
            <tr className="border-b border-line">
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Pixel (x, y)</th>
              <th className="px-4 py-3 font-medium">RA</th>
              <th className="px-4 py-3 font-medium">DEC</th>
              <th className="px-4 py-3 text-right font-medium">Flux</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {objects.map((o, i) => {
              const b = badge(o);
              const sel = selected === i;
              return (
                <tr
                  key={i}
                  ref={(el) => (rowRefs.current[i] = el)}
                  onClick={() => onSelect?.(sel ? null : i)}
                  className={`cursor-pointer border-b border-line/60 transition ${
                    sel ? "bg-cyan/10 ring-1 ring-inset ring-cyan/40" : "hover:bg-panel2/60"
                  }`}
                >
                  <td className="px-4 py-2.5">
                    <span className={`rounded-md border px-2 py-0.5 text-xs ${b.cls}`}>{b.label}</span>
                  </td>
                  <td className="px-4 py-2.5 text-ink/90">{o.x.toFixed(1)}, {o.y.toFixed(1)}</td>
                  <td className="px-4 py-2.5 text-ink/80">{o.ra != null ? o.ra.toFixed(5) + "\u00b0" : "\u2014"}</td>
                  <td className="px-4 py-2.5 text-ink/80">{o.dec != null ? (o.dec >= 0 ? "+" : "") + o.dec.toFixed(5) + "\u00b0" : "\u2014"}</td>
                  <td className="px-4 py-2.5 text-right text-muted">{o.flux != null ? o.flux.toFixed(0) : "\u2014"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// React wrapper for the three.js orbit: one scene for the component's life, updated through its methods
import { useEffect, useRef } from "react";
import { TalentOrbit } from "./talent-orbit.js";

const escapeHtml = (text) =>
  String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// The orbit sets its tooltip as HTML, so everything in it is escaped.
const tooltip = (c) => {
  const score = c.pending ? "not scored" : `${Math.round(c.score * 100)}%`;
  const flag = c.quarantined ? " · flagged" : "";
  return `<strong>${escapeHtml(c.label ?? c.id)}</strong><br>${escapeHtml(c.profile ?? "")} · ${score}${flag}`;
};

export function TalentOrbitView({ data, selectedId, paused, onSelect, onHover }) {
  const container = useRef(null);
  const orbit = useRef(null);
  const handlers = useRef({ onSelect, onHover });
  handlers.current = { onSelect, onHover };

  useEffect(() => {
    const instance = new TalentOrbit(container.current, {
      minScore: 0,
      quarantineOrbit: "score",
      thresholds: [
        { score: 0.75, label: "75%", highlight: true },
        { score: 0.5, label: "50%" },
        { score: 0.25, label: "25%" },
      ],
      tooltip,
    });
    orbit.current = instance;
    const off = [
      instance.on("select", (candidate) => handlers.current.onSelect?.(candidate)),
      instance.on("hover", (candidate) => handlers.current.onHover?.(candidate)),
    ];
    return () => {
      off.forEach((unsubscribe) => unsubscribe());
      instance.destroy();
      orbit.current = null;
    };
  }, []);

  useEffect(() => { orbit.current?.setData(data); }, [data]);
  useEffect(() => { orbit.current?.select(selectedId ?? null); }, [selectedId, data]);
  useEffect(() => { orbit.current?.setPaused(paused); }, [paused]);

  return <div ref={container} className="scr-orbit" role="img" aria-label="Candidates orbiting the job. Closer means a higher score." />;
}

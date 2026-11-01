// Chart tooltip styled like a note pinned in the ledger margin
export function LedgerTooltip({ active, payload, label, format = (v) => v, labelFormat = (l) => l }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="ledger-note" role="status">
      <p className="label">{labelFormat(label)}</p>
      {payload.map((item) => (
        <p key={item.dataKey} className="ledger-note-row">
          <span className="swatch" style={{ background: item.color || item.stroke || item.fill }} aria-hidden="true" />
          <span>{item.name}</span>
          <b>{item.value === null || item.value === undefined ? "hidden" : format(item.value, item.dataKey)}</b>
        </p>
      ))}
    </div>
  );
}

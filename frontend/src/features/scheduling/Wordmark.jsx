// HRwall wordmark: a small wall of offset bricks with one brick missing, like an open gate
export function Wordmark({ subtitle }) {
  const bricks = [
    [0, 0], [11, 0], [22, 0],
    [5.5, 6], [16.5, 6],
    [0, 12], [22, 12], // the middle brick of the bottom row is the open gate
  ];
  return (
    <div className="wordmark">
      <svg viewBox="0 0 32 17" width="40" height="22" aria-hidden="true">
        {bricks.map(([x, y]) => (
          <rect key={`${x}-${y}`} x={x} y={y} width="10" height="5" rx="0.6" />
        ))}
        <rect className="gate" x="11" y="12" width="10" height="5" rx="0.6" />
      </svg>
      <span className="wordmark-name">HRwall</span>
      {subtitle && <span className="wordmark-sub">{subtitle}</span>}
    </div>
  );
}

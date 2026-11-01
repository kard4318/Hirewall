// Department x quarter attrition heatmap in CSS grid; every cell prints its value, suppressed cells are hatched
import { pct } from "../chartTheme.jsx";
import { groupSize, quarter } from "../../../shared/format.js";

function tone(rate, max) {
  if (rate === null || rate === undefined) return 0;
  return Math.min(1, rate / Math.max(max, 0.0001));
}

export function Heatmap({ matrix, quarters }) {
  const values = matrix.flatMap((row) => row.cells.filter((c) => !c.suppressed).map((c) => c.rate || 0));
  const max = Math.max(0.05, ...values);
  return (
    <div className="heatmap-wrap">
      <table className="heatmap">
        <caption className="visually-hidden">Quarterly attrition rate by department; hatched cells have fewer than 5 people.</caption>
        <thead>
          <tr><th scope="col"><span className="visually-hidden">Department</span></th>
            {quarters.map((q) => <th key={q} scope="col">{quarter(q, { short: true })}</th>)}</tr>
        </thead>
        <tbody>
          {matrix.map((row) => (
            <tr key={row.department}>
              <th scope="row">{row.department}</th>
              {row.cells.map((cell) => (
                <td key={cell.quarter} className={cell.suppressed ? "is-suppressed" : ""}
                  style={cell.suppressed ? undefined : { "--heat": tone(cell.rate, max) }}
                  title={cell.suppressed ? "Group too small to show" : `${row.department}, ${quarter(cell.quarter)}: ${pct(cell.rate)} (${cell.exits} exits, ${groupSize(cell.n)})`}>
                  {cell.suppressed ? <span aria-label="hidden">·</span> : pct(cell.rate, 0)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="heatmap-legend"><span className="heat-key low" /> lower <span className="heat-key high" /> higher
        <span className="heat-key hatched" /> group too small to show</p>
    </div>
  );
}

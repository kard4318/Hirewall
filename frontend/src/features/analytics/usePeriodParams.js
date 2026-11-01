// Turns the filter-bar state into API parameters (from/to relative to the data's as_of date)
import { useMemo } from "react";
import { daysBefore, PERIODS } from "./api.js";

export function usePeriodParams(filters, asOf) {
  return useMemo(() => {
    if (!asOf) return null;
    const days = PERIODS.find((p) => p.id === filters.period)?.days ?? 365;
    return { from: daysBefore(asOf, days), to: asOf, department: filters.department, site: filters.site,
      contract: filters.contract };
  }, [filters, asOf]);
}

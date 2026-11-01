// /hr/* routes: passcode gate first, then the HR shell (Overview, People, Retention, Scheduling); token in sessionStorage
import { lazy, Suspense, useCallback, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { HrShell } from "../../analytics/HrShell.jsx";
import { hrSession } from "../api.js";
import { HrDashboard } from "./HrDashboard.jsx";
import { PasscodeGate } from "./PasscodeGate.jsx";
import { QuestionDesk } from "../../knowledge/hr/QuestionDesk.jsx";
import "../styles/base.css";
import "../styles/hr.css";

// Analytics pages (and recharts) load only when HR opens them, keeping the candidate and employee pages light.
const OverviewPage = lazy(() => import("../../analytics/pages/OverviewPage.jsx").then((m) => ({ default: m.OverviewPage })));
const PeoplePage = lazy(() => import("../../analytics/pages/PeoplePage.jsx").then((m) => ({ default: m.PeoplePage })));
const RetentionPage = lazy(() => import("../../analytics/pages/RetentionPage.jsx").then((m) => ({ default: m.RetentionPage })));
const InboxPage = lazy(() => import("../../inbox/InboxPage.jsx").then((m) => ({ default: m.InboxPage })));
const DirectoryPage = lazy(() => import("../../analytics/pages/DirectoryPage.jsx").then((m) => ({ default: m.DirectoryPage })));
const loading = <main className="a-page"><div className="skeleton" aria-busy="true"><span /><span /><span /></div></main>;

export function HrPage() {
  const [token, setToken] = useState(() => hrSession.get());

  const signIn = (value) => {
    hrSession.set(value);
    setToken(value);
  };
  const signOut = useCallback(() => {
    hrSession.clear();
    setToken(null);
  }, []);

  if (!token) return <PasscodeGate onToken={signIn} />;
  return (
    <Routes>
      <Route element={<HrShell token={token} onSignOut={signOut} />}>
        <Route index element={<Navigate to="overview" replace />} />
        <Route path="overview" element={<Suspense fallback={loading}><OverviewPage /></Suspense>} />
        <Route path="people" element={<Suspense fallback={loading}><PeoplePage /></Suspense>} />
        <Route path="retention" element={<Suspense fallback={loading}><RetentionPage /></Suspense>} />
        <Route path="directory" element={<Suspense fallback={loading}><DirectoryPage /></Suspense>} />
        <Route path="scheduling" element={<HrDashboard token={token} onSignOut={signOut} embedded />} />
        <Route path="inbox" element={<Suspense fallback={loading}><InboxPage /></Suspense>} />
        <Route path="questions" element={<QuestionDesk token={token} onError={(err) => err.status === 401 && signOut()} />} />
        <Route path="*" element={<Navigate to="overview" replace />} />
      </Route>
    </Routes>
  );
}

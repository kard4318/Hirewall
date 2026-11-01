// Root component with layout and page routing
import { Navigate, Route, Routes } from "react-router-dom";
import { JobApplyPage } from "./features/apply/JobApplyPage.jsx";
import { JobsListPage } from "./features/apply/JobsListPage.jsx";
import { HomePage } from "./features/home/HomePage.jsx";
import { AskPage } from "./features/knowledge/employee/AskPage.jsx";
import { CandidatePage } from "./features/scheduling/candidate/CandidatePage.jsx";
import { HrPage } from "./features/scheduling/hr/HrPage.jsx";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/hr/*" element={<HrPage />} />
      <Route path="/candidate" element={<CandidatePage />} />
      <Route path="/ask" element={<AskPage />} />
      <Route path="/jobs" element={<JobsListPage />} />
      <Route path="/jobs/:jobId" element={<JobApplyPage />} />
      <Route path="/employee" element={<Navigate to="/ask" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

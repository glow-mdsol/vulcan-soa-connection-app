import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { getContext } from "./api/client";
import type { Context } from "./api/types";
import LaunchError from "./launch/LaunchError";
import LaunchPending from "./launch/LaunchPending";
import Enroll from "./views/Enroll/Enroll";
import StudyWorklist from "./views/StudyWorklist/StudyWorklist";
import SubjectDashboard from "./views/SubjectDashboard/SubjectDashboard";

function Landing() {
  const [context, setContext] = useState<Context | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getContext()
      .then(setContext)
      .catch(() => setFailed(true));
  }, []);

  if (failed) {
    return (
      <p>
        No active session. Launch this app from your EHR, or{" "}
        <a href="/launch/standalone">start a standalone launch</a>.
      </p>
    );
  }

  if (!context) {
    return <LaunchPending />;
  }

  if (context.researchStudyId) {
    return <Navigate to={`/enroll/${context.researchStudyId}`} replace />;
  }

  return <StudyWorklist />;
}

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/launch-error" element={<LaunchError />} />
      <Route path="/enroll/:studyId" element={<Enroll />} />
      <Route path="/subjects/:subjectId" element={<SubjectDashboard />} />
    </Routes>
  );
}

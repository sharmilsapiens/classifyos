/* The route table. Each URL maps to a page; all pages render inside <AppLayout>
   (sidebar + topbar). 9a built Overview / Upload / Configuration; 9b added the
   result pages (Feature Impact, Interactions, Confusion, Class Report, ROC/PR,
   Predictions); 9c added the last three (Explainability, Setup, Risks) and MERGED
   the old Pipeline page into Overview — so /pipeline now redirects to "/". */

import { Navigate, Route, Routes } from "react-router-dom"

import { AppLayout } from "@/components/layout/AppLayout"
import Overview from "@/pages/Overview"
import UploadPage from "@/pages/Upload"
import DataProfile from "@/pages/DataProfile"
import Configure from "@/pages/Configure"
import Runs from "@/pages/Runs"
import FeatureImpact from "@/pages/FeatureImpact"
// TEMPORARILY HIDDEN — interaction features unwired from the backend.
// import Interactions from "@/pages/Interactions"
import ConfusionMatrix from "@/pages/ConfusionMatrix"
import ClassReport from "@/pages/ClassReport"
import Curves from "@/pages/Curves"
import Predictions from "@/pages/Predictions"
import FitDiagnostics from "@/pages/FitDiagnostics"
import TuningResults from "@/pages/TuningResults"
import Explainability from "@/pages/Explainability"
import SetupGuide from "@/pages/SetupGuide"
import RiskRegister from "@/pages/RiskRegister"
import NotFound from "@/pages/NotFound"

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {/* Workspace screens */}
        <Route path="/" element={<Overview />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/data-profile" element={<DataProfile />} />
        <Route path="/configure" element={<Configure />} />
        {/* Runs — past runs read back from MLflow (schema 1.10, Interim 2a). */}
        <Route path="/runs" element={<Runs />} />
        {/* 9c: Pipeline merged into Overview — keep the old link working. */}
        <Route path="/pipeline" element={<Navigate to="/" replace />} />

        {/* Result pages (9b) */}
        <Route path="/feature-impact" element={<FeatureImpact />} />
        {/* TEMPORARILY HIDDEN — interaction features unwired. Redirect stale links. */}
        {/* <Route path="/interactions" element={<Interactions />} /> */}
        <Route path="/interactions" element={<Navigate to="/" replace />} />
        <Route path="/confusion" element={<ConfusionMatrix />} />
        <Route path="/class-report" element={<ClassReport />} />
        <Route path="/curves" element={<Curves />} />
        <Route path="/predictions" element={<Predictions />} />
        <Route path="/diagnostics" element={<FitDiagnostics />} />
        <Route path="/tuning" element={<TuningResults />} />
        <Route path="/explainability" element={<Explainability />} />

        {/* Reference pages (9c) */}
        <Route path="/setup" element={<SetupGuide />} />
        <Route path="/risks" element={<RiskRegister />} />

        {/* Anything else */}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

export default App

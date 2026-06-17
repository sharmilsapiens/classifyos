/* The route table. Each URL maps to a page; all pages render inside <AppLayout>
   (sidebar + topbar). 9a built Overview / Upload / Configuration; 9b added the
   result pages (Feature Impact, Interactions, Confusion, Class Report, ROC/PR,
   Predictions); 9c added the last three (Explainability, Setup, Risks) and MERGED
   the old Pipeline page into Overview — so /pipeline now redirects to "/". */

import { Navigate, Route, Routes } from "react-router-dom"

import { AppLayout } from "@/components/layout/AppLayout"
import Overview from "@/pages/Overview"
import UploadPage from "@/pages/Upload"
import Configure from "@/pages/Configure"
import FeatureImpact from "@/pages/FeatureImpact"
import Interactions from "@/pages/Interactions"
import ConfusionMatrix from "@/pages/ConfusionMatrix"
import ClassReport from "@/pages/ClassReport"
import Curves from "@/pages/Curves"
import Predictions from "@/pages/Predictions"
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
        <Route path="/configure" element={<Configure />} />
        {/* 9c: Pipeline merged into Overview — keep the old link working. */}
        <Route path="/pipeline" element={<Navigate to="/" replace />} />

        {/* Result pages (9b) */}
        <Route path="/feature-impact" element={<FeatureImpact />} />
        <Route path="/interactions" element={<Interactions />} />
        <Route path="/confusion" element={<ConfusionMatrix />} />
        <Route path="/class-report" element={<ClassReport />} />
        <Route path="/curves" element={<Curves />} />
        <Route path="/predictions" element={<Predictions />} />
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

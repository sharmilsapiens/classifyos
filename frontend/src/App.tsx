/* The route table. Each URL maps to a page; all pages render inside <AppLayout>
   (sidebar + topbar). 9a built Overview / Upload / Configuration / Pipeline; 9b
   adds the result pages (Feature Impact, Interactions, Confusion, Class Report,
   ROC/PR, Predictions). The remaining entries (Explainability, Setup, Risks) are
   still stub routes, filled in during 9c. */

import { Route, Routes } from "react-router-dom"

import { AppLayout } from "@/components/layout/AppLayout"
import { NAV_ITEMS } from "@/lib/nav"
import Overview from "@/pages/Overview"
import UploadPage from "@/pages/Upload"
import Configure from "@/pages/Configure"
import Pipeline from "@/pages/Pipeline"
import FeatureImpact from "@/pages/FeatureImpact"
import Interactions from "@/pages/Interactions"
import ConfusionMatrix from "@/pages/ConfusionMatrix"
import ClassReport from "@/pages/ClassReport"
import Curves from "@/pages/Curves"
import Predictions from "@/pages/Predictions"
import { StubPage } from "@/pages/StubPage"
import NotFound from "@/pages/NotFound"

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {/* Workspace screens (9a) */}
        <Route path="/" element={<Overview />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/configure" element={<Configure />} />
        <Route path="/pipeline" element={<Pipeline />} />

        {/* Result pages (9b) */}
        <Route path="/feature-impact" element={<FeatureImpact />} />
        <Route path="/interactions" element={<Interactions />} />
        <Route path="/confusion" element={<ConfusionMatrix />} />
        <Route path="/class-report" element={<ClassReport />} />
        <Route path="/curves" element={<Curves />} />
        <Route path="/predictions" element={<Predictions />} />

        {/* Stub routes — remaining nav entries render a placeholder (9c). */}
        {NAV_ITEMS.filter((item) => item.stub).map((item) => (
          <Route key={item.path} path={item.path} element={<StubPage item={item} />} />
        ))}

        {/* Anything else */}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

export default App

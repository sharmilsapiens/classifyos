/* The route table. Each URL maps to a page; all pages render inside <AppLayout>
   (sidebar + topbar). Only Overview / Upload / Configuration / Pipeline are real
   screens in 9a — the remaining nav entries are stub routes filled in 9b/9c. */

import { Route, Routes } from "react-router-dom"

import { AppLayout } from "@/components/layout/AppLayout"
import { NAV_ITEMS } from "@/lib/nav"
import Overview from "@/pages/Overview"
import UploadPage from "@/pages/Upload"
import Configure from "@/pages/Configure"
import Pipeline from "@/pages/Pipeline"
import { StubPage } from "@/pages/StubPage"
import NotFound from "@/pages/NotFound"

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {/* Real screens (9a) */}
        <Route path="/" element={<Overview />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/configure" element={<Configure />} />
        <Route path="/pipeline" element={<Pipeline />} />

        {/* Stub routes — every other nav entry renders a placeholder for now. */}
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

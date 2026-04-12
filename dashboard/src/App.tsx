import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import { AppProvider } from "@/contexts/AppContext";
import { Layout } from "@/components/Layout";
import { Dashboard } from "@/pages/Dashboard";
import { Sandboxes } from "@/pages/Sandboxes";
import { SandboxDetail } from "@/pages/SandboxDetail";
import { Templates } from "@/pages/Templates";
import { TemplateDetail } from "@/pages/TemplateDetail";
import { Pools } from "@/pages/Pools";
import { Webhooks } from "@/pages/Webhooks";
import { TerminalPage } from "@/pages/TerminalPage";

export default function App() {
  return (
    <AppProvider>
      <Router>
        <Routes>
          {/* Fullscreen terminal — rendered without Layout chrome */}
          <Route path="/sandboxes/:sandboxId/terminal" element={<TerminalPage />} />

          {/* All other pages — wrapped in Layout (header + nav + footer) */}
          <Route
            path="*"
            element={
              <Layout>
                <Routes>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/sandboxes" element={<Sandboxes />} />
                  <Route path="/sandboxes/:sandboxId" element={<SandboxDetail />} />
                  <Route path="/templates" element={<Templates />} />
                  <Route path="/templates/:templateId" element={<TemplateDetail />} />
                  <Route path="/pools" element={<Pools />} />
                  <Route path="/webhooks" element={<Webhooks />} />
                </Routes>
              </Layout>
            }
          />
        </Routes>
      </Router>
    </AppProvider>
  );
}

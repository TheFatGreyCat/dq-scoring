import { MonitorPage } from "../features/operations/MonitorPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { TemplateCatalogPage } from "../features/templates/TemplateCatalogPage";
import { createBrowserRouter, Link } from "react-router";
import { AppShell } from "./AppShell";
import { AssetsPage } from "../features/assets/AssetsPage";
import { SnapshotDetailPage } from "../features/assets/SnapshotDetailPage";
import { AssessmentsPage, ScorecardPage } from "../features/assessments/ScorecardPage";
import { PublicScorecardPage } from "../features/assessments/PublicScorecardPage";
import { LoginPage } from "../features/auth/LoginPage";
import { RequireAuth } from "../features/auth/RequireAuth";
import { PoliciesPage } from "../features/governance/PoliciesPage";
import { RulesetsPage } from "../features/governance/RulesetsPage";
import { OverviewPage } from "../features/OverviewPage";
import { RunStatusPage } from "../features/runs/RunStatusPage";
import { RunWizardPage } from "../features/runs/RunWizardPage";
import { RunsPage } from "../features/runs/RunsPage";
import { useI18n } from "../lib/i18n";

function NotFound() {
  const { t } = useI18n();
  return (
    <div className="card text-center py-12">
      <h1>{t("common.not_found")}</h1>
      <Link to="/" className="mt-4 inline-block text-action font-semibold">{t("nav.overview")}</Link>
    </div>
  );
}

export const routes = [
  { path: "/login", element: <LoginPage /> },
  { path: "/public/assessments/:assessmentId", element: <PublicScorecardPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <OverviewPage /> },
          { path: "assets", element: <AssetsPage /> },
          { path: "snapshots/:snapshotId", element: <SnapshotDetailPage /> },
          { path: "rulesets", element: <RulesetsPage /> },
          { path: "policies", element: <PoliciesPage /> },
          { path: "templates", element: <TemplateCatalogPage /> },
          { path: "runs", element: <RunsPage /> },
          { path: "runs/new", element: <RunWizardPage /> },
          { path: "runs/:runId", element: <RunStatusPage /> },
          { path: "assessments", element: <AssessmentsPage /> },
          { path: "assessments/:assessmentId", element: <ScorecardPage /> },
          { path: "settings", element: <SettingsPage /> },
          { path: "monitor", element: <MonitorPage /> },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);

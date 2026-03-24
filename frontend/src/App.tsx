import { BrowserRouter, Routes, Route } from "react-router";
import { Provider } from "urql";
import { client } from "@/lib/urql";
import { lazy, Suspense } from "react";
import { LoadingState } from "@/components/LoadingState";
import { AppShell } from "@/components/AppShell";

const EnvironmentListPage = lazy(
  () => import("@/pages/environments/EnvironmentListPage"),
);
const EnvironmentDetailPage = lazy(
  () => import("@/pages/environments/EnvironmentDetailPage"),
);
const DeployFormPage = lazy(() => import("@/pages/deployments/DeployFormPage"));
const DeploymentDetailPage = lazy(
  () => import("@/pages/deployments/DeploymentDetailPage"),
);
const DriverListPage = lazy(() => import("@/pages/drivers/DriverListPage"));
const DriverDetailPage = lazy(() => import("@/pages/drivers/DriverDetailPage"));
const AddDriverPage = lazy(() => import("@/pages/drivers/AddDriverPage"));
const BackupStorageLocationListPage = lazy(
  () =>
    import("@/pages/backup-storage-locations/BackupStorageLocationListPage"),
);
const BackupStorageLocationDetailPage = lazy(
  () =>
    import("@/pages/backup-storage-locations/BackupStorageLocationDetailPage"),
);
const SettingsPage = lazy(() => import("@/pages/settings/SettingsPage"));
const ClusterDetailPage = lazy(
  () => import("@/pages/settings/ClusterDetailPage"),
);

export default function App() {
  return (
    <Provider value={client}>
      <BrowserRouter>
        <Suspense fallback={<LoadingState />}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<EnvironmentListPage />} />
              <Route
                path="/environments/:environmentId"
                element={<EnvironmentDetailPage />}
              />
              <Route
                path="/environments/:environmentId/deploy"
                element={<DeployFormPage />}
              />
              <Route
                path="/environments/:environmentId/deployments/:deploymentId"
                element={<DeploymentDetailPage />}
              />
              <Route
                path="/backup-storage-locations"
                element={<BackupStorageLocationListPage />}
              />
              <Route
                path="/backup-storage-locations/:id"
                element={<BackupStorageLocationDetailPage />}
              />
              <Route path="/drivers" element={<DriverListPage />} />
              <Route path="/drivers/add" element={<AddDriverPage />} />
              <Route path="/drivers/:driverId" element={<DriverDetailPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route
                path="/settings/clusters/:clusterId"
                element={<ClusterDetailPage />}
              />
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </Provider>
  );
}

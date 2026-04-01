# Import Migration Contract

All React Router imports must be replaced with TanStack Router equivalents. Zero `react-router` imports may remain after migration.

## Import Mapping

| React Router Import | TanStack Router Import |
|---------------------|----------------------|
| `import { BrowserRouter, Routes, Route } from 'react-router'` | `import { RouterProvider } from '@tanstack/react-router'` |
| `import { Link } from 'react-router'` | `import { Link } from '@tanstack/react-router'` |
| `import { useParams } from 'react-router'` | `import { useParams } from '@tanstack/react-router'` (or `Route.useParams()`) |
| `import { useNavigate } from 'react-router'` | `import { useNavigate } from '@tanstack/react-router'` |
| `import { useLocation } from 'react-router'` | `import { useRouterState } from '@tanstack/react-router'` |
| `import { Outlet } from 'react-router'` | `import { Outlet } from '@tanstack/react-router'` |
| `import { MemoryRouter } from 'react-router'` | `import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'` |

## Files Requiring Changes

| File | Imports to Replace |
|------|-------------------|
| `src/App.tsx` | `BrowserRouter`, `Routes`, `Route` |
| `src/components/AppShell.tsx` | `Outlet`, `Link`, `useLocation` |
| `src/components/PageLayout.tsx` | `Link` |
| `src/pages/environments/EnvironmentListPage.tsx` | `Link` |
| `src/pages/environments/EnvironmentDetailPage.tsx` | `useParams`, `useNavigate`, `Link` |
| `src/pages/deployments/DeployFormPage.tsx` | `useParams`, `useNavigate`, `Link` |
| `src/pages/deployments/DeploymentDetailPage.tsx` | `useParams`, `useNavigate` |
| `src/pages/drivers/DriverListPage.tsx` | `useNavigate`, `Link` |
| `src/pages/drivers/DriverDetailPage.tsx` | `useParams` |
| `src/pages/drivers/AddDriverPage.tsx` | `useNavigate` |
| `src/pages/backup-storage-locations/BackupStorageLocationListPage.tsx` | `Link` |
| `src/pages/backup-storage-locations/BackupStorageLocationDetailPage.tsx` | `useParams`, `useNavigate` |
| `src/pages/settings/SettingsPage.tsx` | `Link` |
| `src/pages/settings/ClusterDetailPage.tsx` | `useParams`, `Link` |
| `src/test/utils.tsx` | `MemoryRouter` |

## Validation

After migration, the following must return zero results:
```bash
grep -r "from ['\"]react-router" frontend/src/
```

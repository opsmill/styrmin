import { rootRoute } from "./routes/__root";
import { indexRoute } from "./routes/index";
import { loginRoute } from "./routes/login";
import { environmentDetailRoute } from "./routes/environmentDetail";
import { deployFormRoute } from "./routes/deployForm";
import { deploymentDetailRoute } from "./routes/deploymentDetail";
import { backupStorageLocationListRoute } from "./routes/backupStorageLocationList";
import { backupStorageLocationDetailRoute } from "./routes/backupStorageLocationDetail";
import { driverListRoute } from "./routes/driverList";
import { addDriverRoute } from "./routes/addDriver";
import { driverDetailRoute } from "./routes/driverDetail";
import { settingsRoute } from "./routes/settings";
import { clusterDetailRoute } from "./routes/clusterDetail";
import { usersListRoute } from "./routes/usersList";
import { userDetailRoute } from "./routes/userDetail";

export const routeTree = rootRoute.addChildren([
  indexRoute,
  loginRoute,
  environmentDetailRoute,
  deployFormRoute,
  deploymentDetailRoute,
  backupStorageLocationListRoute,
  backupStorageLocationDetailRoute,
  driverListRoute,
  addDriverRoute,
  driverDetailRoute,
  settingsRoute,
  clusterDetailRoute,
  usersListRoute,
  userDetailRoute,
]);

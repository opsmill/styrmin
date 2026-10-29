# Semaphore driver (worked example)

Deploys Ansible Semaphore with the `semaphoreui/semaphore` chart 16.0.11 and its Bitnami
PostgreSQL subchart.

| Component | Workload | Backup |
|---|---|---|
| `server` | Deployment `styrmin-semaphore`, container `semaphore`, port 3000 | none: data is in PostgreSQL |
| `database` | StatefulSet `styrmin-postgresql`, container `postgresql`, singleton | `postgres` (pg_dump to `/backup`) |

- Service `semaphore` (external): the chart's Ingress serves `primary_fqdn` and `human_readable_fqdn`.
- Network: a NetworkPolicy shipped through `postgresql.extraDeploy` allows DNS, the namespace's
  pods and the internet without private ranges.
- Credentials: admin `admin` / `admin-password`, database `semaphore` / `semaphore-db-password`.
  Change them in `values.j2.yml` before a real deployment.

Checked: `check_driver.py --check-images` 0 FAIL 0 WARN. Deployed on Styrmin 0.1.54 (kind, network
policies enforced): both pods Ready in under 60 s, the URL answered HTTP 200, and the admin login
answered 204. Not checked: backup and restore, upgrade.

```bash
styrminctl drivers load-version <git-url> main --driver-directory semaphore
styrminctl deployments create semaphore 2.16.47 <environment> --cluster <cluster>
```

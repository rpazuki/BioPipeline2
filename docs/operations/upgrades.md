# Updating BioPipeline2 from Git

`git pull` updates source files only. Backend changes also need package
installation and service restarts; frontend changes need a new production build.
Database schema changes need Alembic migrations. Changes must be committed and
pushed to GitHub before another machine can pull them.

These commands target the `/opt/biopipeline2` systemd installation, including
RHEL. Run blocks in order in the same Bash shell, stopping on any failure.
The standard procedure below uses a maintenance window for both ordinary updates
and database updates. It stops processes before replacing their code or build.

## 1. Check the checkout and incoming changes

```bash
cd /opt/biopipeline2
sudo -u biopipeline git status --short
sudo -u biopipeline git branch --show-current
sudo -u biopipeline git rev-parse HEAD
sudo -u biopipeline git fetch origin
sudo -u biopipeline git log --oneline 'HEAD..@{upstream}'
sudo -u biopipeline git diff --name-only 'HEAD..@{upstream}'
```

Record the current commit for recovery. These commands assume a branch tracking
its intended remote branch, normally `main`. If the checkout is detached at a
release tag, select the intended release explicitly instead of using `git pull`.

**Stop if there are local edits.** Earlier server-side fixes may need to be
merged with the incoming changes. Do not use `git reset --hard` or discard them.
Inspect incoming changes under `backend/alembic/versions/`, release instructions,
settings and `deploy/`. Review migration code before applying it, especially any
column removal, rename or data transformation. Do not infer that a database is
current solely because the latest Git update has no new migration files.

## 2. Stop submissions and drain workers

```bash
# Remember which worker instances were running; restore those same instances later.
mapfile -t BP_UPDATE_WORKERS < <(
    systemctl list-units --type=service --state=active --plain --no-legend \
        'biopipeline2-worker@*.service' | awk '{print $1}'
)

sudo systemctl stop biopipeline2-reconcile.timer
sudo systemctl stop biopipeline2-api biopipeline2-frontend biopipeline2-scheduler
if ((${#BP_UPDATE_WORKERS[@]})); then
    sudo systemctl stop "${BP_UPDATE_WORKERS[@]}"
fi
sudo systemctl stop biopipeline2-reaper biopipeline2-courier biopipeline2-reconcile.service
```

Worker shutdown drains running work and can take hours. The supplied timeout is
12 hours; increase `TimeoutStopSec` beforehand if a task can take longer. Check
that workers finished cleanly before continuing; do not force-kill them. API and
frontend requests are unavailable during this maintenance window.

Take a database and storage backup now, following
[backup-and-restore.md](backup-and-restore.md). Record the database's current
migration revision and retain the backup before any schema change. Do not proceed
with a database update unless the backup succeeded.

## 3. Pull and install the backend

```bash
cd /opt/biopipeline2
sudo -u biopipeline git pull --ff-only
sudo -u biopipeline git log -1 --oneline
sudo -u biopipeline .venv/bin/python -m pip install ./backend
sudo -u biopipeline .venv/bin/python -m pip check
sudo -u biopipeline .venv/bin/uvicorn --version
```

If Git reports divergent history or conflicting local edits, stop and resolve
that checkout deliberately. If installation fails, keep services stopped until
it is repaired or the previous release is restored.

## 4. Database updates (or confirm no update is needed)

Use the same environment file and account as the API. Merely running Alembic in
the repository directory does not load `/etc/biopipeline2/biopipeline2.env`.

```bash
sudo systemd-run --wait --pipe --collect --uid=biopipeline \
    --property=EnvironmentFile=/etc/biopipeline2/biopipeline2.env \
    --working-directory=/opt/biopipeline2/backend \
    /opt/biopipeline2/.venv/bin/alembic current

sudo systemd-run --wait --pipe --collect --uid=biopipeline \
    --property=EnvironmentFile=/etc/biopipeline2/biopipeline2.env \
    --working-directory=/opt/biopipeline2/backend \
    /opt/biopipeline2/.venv/bin/alembic heads
```

- **Ordinary update, no pending schema changes:** if the database's current
  revision matches the repository head, continue to section 5. Running the
  upgrade command below is also safe in this case: it has no migrations to apply.
- **Database update:** after reviewing the pending migrations and taking the
  backup, run the command below. Do not restart services if it fails.

```bash
sudo systemd-run --wait --pipe --collect --uid=biopipeline \
    --property=EnvironmentFile=/etc/biopipeline2/biopipeline2.env \
    --working-directory=/opt/biopipeline2/backend \
    /opt/biopipeline2/.venv/bin/alembic upgrade head

sudo systemd-run --wait --pipe --collect --uid=biopipeline \
    --property=EnvironmentFile=/etc/biopipeline2/biopipeline2.env \
    --working-directory=/opt/biopipeline2/backend \
    /opt/biopipeline2/.venv/bin/alembic current
```

Verify the reported revision matches `alembic heads`. Multiple heads require an
explicit release migration plan; do not choose one arbitrarily. Passwords in
`BP_DATABASE_URL` stay URL-encoded (`%40` for `@`); the migration loader escapes
percent signs internally for Alembic's configuration parser.

## 5. Rebuild the frontend

```bash
cd /opt/biopipeline2/frontend
sudo -u biopipeline npm ci

# Match BP_BASE_PATH in the deployment environment file; empty for a root-mounted app.
BP_UPDATE_BASE_PATH=''
sudo -u biopipeline env NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_BASE_PATH="$BP_UPDATE_BASE_PATH" npm run build

if [ -d public ]; then
    sudo -u biopipeline cp -a public .next/standalone/
fi
sudo -u biopipeline cp -a .next/static .next/standalone/.next/
```

`public` is optional and currently absent from the repository. The conditional
skips it; copying `.next/static` is still required.


Continue only if both installation and build succeed. Do not use
`npm audit fix --force` as part of a deployment. For backend-only releases this
step can be skipped if the existing frontend build is compatible and no
frontend or API contract changes require rebuilding it.

## 6. Deploy any changed runtime configuration, then start services

For ordinary code-only updates, leave the existing systemd units and nginx
configuration in place. They may contain site-specific settings.

If the release changes systemd units, review and install those changed files
from `deploy/systemd/` into `/etc/systemd/system/`, then reload systemd:

```bash
sudo systemctl daemon-reload
```

Keep existing drop-ins, including a frontend `PORT=3100` override or telemetry
settings. A frontend rebuild does not change that service port. Keep nginx's
frontend proxy pointing at the same port. If a new task image is required,
build it with a new version tag and update `BP_TASK_DEFAULT_IMAGE` before starting
workers. Merge any new settings into the existing environment file; do not
replace it with the example file or overwrite secrets.

```bash
sudo systemctl start biopipeline2-api biopipeline2-frontend \
    biopipeline2-scheduler biopipeline2-reaper biopipeline2-courier
if ((${#BP_UPDATE_WORKERS[@]})); then
    sudo systemctl start "${BP_UPDATE_WORKERS[@]}"
fi
sudo systemctl start biopipeline2-reconcile.timer
```

The worker array must come from section 2 in this same shell. If the connection
was lost, explicitly start the worker instances you recorded before maintenance.
Do not start additional workers automatically.

No nginx restart is needed for application code updates. If nginx configuration
was deliberately changed, run `sudo nginx -t && sudo systemctl reload nginx`.

## 7. Verify the update

```bash
curl --noproxy '*' --fail --silent --show-error --retry 30 --retry-delay 2 \
    --retry-connrefused --retry-max-time 60 http://127.0.0.1:8000/ready

sudo systemctl --no-pager --full status biopipeline2-api biopipeline2-frontend
sudo journalctl -u biopipeline2-api -u biopipeline2-frontend \
    --since '10 minutes ago' --no-pager
```

The readiness response should report all checks as `ok`. It checks database
connectivity and storage directories, not the migration revision; section 4 is
still required. Check the configured hostname and port in a browser (for example
`https://rlalab-assist.dept.ic.ac.uk:8443/login`), sign in, and submit a small
pipeline through completion and download. Watch workers and queued work in Admin.
Certificate trust must be resolved independently; do not treat `curl -k` as a
successful TLS verification.

## If a task must survive an upgrade

Schedule the maintenance after it completes whenever possible. Do not install
new code into this shared checkout or virtual environment while relying on an
old worker to keep running unchanged: it can still import code or start child
processes from those paths. Concurrent versions need separate release directories,
virtual environments, and a reviewed database compatibility plan. Non-additive
schema changes require draining all processes that use the old schema.

## If an update fails or must be rolled back

Keep services stopped while resolving a failed install, build or migration.
Prefer a forward fix when possible. For a code-only rollback, select the recorded
previous commit, reinstall its backend, rebuild its frontend, and start services
as above. Preserve deployment settings and drop-ins.

After a schema update, reverting Git alone is insufficient. Stop all database
writers and follow the release's tested downgrade plan, or restore the
pre-upgrade database/storage backup and matching code. Never run a guessed
`alembic downgrade`: removing columns can destroy data. A database rollback also
needs compatible artifact/storage state; follow the backup/restore guide.

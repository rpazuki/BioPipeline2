# Fresh installation on Red Hat Enterprise Linux

This guide targets RHEL 9.6+ in the RHEL 9 series, with sudo access, a local
PostgreSQL database, Docker Engine, and a dedicated hostname. Run the blocks
in order in Bash; stop when a required command fails. RHEL 8/10 and PostgreSQL
from PGDG, containers or a remote server need different package/service steps.
These commands have not been executed on the target RHEL host.

Use a Git revision containing `bp-create-admin` and the Uvicorn runtime dependency.
Commit and push local deployment changes before installing from another machine.
The default public port below is HTTPS 8443, leaving port 80 untouched. Internal
API/frontend ports remain 8000/3000. An existing web server can instead proxy to them.

## 1. Inspect before installing

```bash
cat /etc/redhat-release
uname -m
free -h
df -h /opt /var/lib
sudo subscription-manager identity

for cmd in git python3.12 node npm docker podman psql nginx; do
    if command -v "$cmd" >/dev/null 2>&1; then
        command -v "$cmd"
        "$cmd" --version
    else
        echo "$cmd: not installed"
    fi
done
rpm -qa | sort | grep -E '^(postgresql|docker|podman|containerd|nodejs|nginx)' || true
sudo systemctl --no-pager status docker postgresql nginx || true
sudo ss -lntp | grep -E ':(80|443|8443|3000|5432|8000)\b' || true
getenforce
```

Review occupied ports and existing services before proceeding. Do not replace
another application's database, container runtime, Node installation or nginx
configuration. The examples below assume RHEL's `postgresql.service`.

## 2. Utilities and Python

```bash
for package in git curl rsync openssl policycoreutils-python-utils container-selinux; do
    rpm -q "$package" >/dev/null 2>&1 || sudo dnf install -y "$package"
done
command -v python3.12 >/dev/null 2>&1 || sudo dnf install -y python3.12
python3.12 -m pip --version >/dev/null 2>&1 || sudo dnf install -y python3.12-pip
python3.12 --version
```

Keep the system Python unchanged. See [Red Hat's Python guide](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html-single/installing_and_using_dynamic_programming_languages/installing_and_using_dynamic_programming_languages).

## 3. Node.js

```bash
if command -v node >/dev/null 2>&1; then
    node --version
    node -e 'if (+process.versions.node.split(".")[0] < 22) { console.error("Node 22+ required; review the existing installation before upgrading."); process.exit(1); }'
else
    sudo dnf module install -y nodejs:22
fi
node --version
npm --version
test -x /usr/bin/node
```

Stop if the version check fails. The frontend unit uses `/usr/bin/node`; an
installation under a user's home directory will not work with `ProtectHome=true`.

## 4. Docker Engine

Use [Docker's RHEL repository](https://docs.docker.com/engine/install/rhel/).
If `docker` already exists, verify that it is actual Docker Engine rather than
`podman-docker`. Do not remove conflicting packages automatically.

```bash
if ! command -v docker >/dev/null 2>&1; then
    rpm -q dnf-plugins-core >/dev/null 2>&1 || sudo dnf install -y dnf-plugins-core
    sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
    sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin
fi
docker --version
sudo systemctl enable --now docker
sudo docker info
```

Stop if the daemon check fails. A Docker CLI alone is insufficient.

## 5. PostgreSQL

For RHEL's local PostgreSQL packages only. If inspection found another existing
installation, use its service name, administrator and data directory instead.
Never initialize over an existing cluster or switch its module stream blindly.

```bash
if ! rpm -q postgresql-server >/dev/null 2>&1; then
    sudo dnf module install -y postgresql:16/server
fi
rpm -q postgresql-contrib >/dev/null 2>&1 || sudo dnf install -y postgresql-contrib
if ! sudo test -f /var/lib/pgsql/data/PG_VERSION; then
    sudo postgresql-setup --initdb
fi
sudo systemctl enable --now postgresql
sudo -u postgres psql -X -c 'SELECT version();'

if ! sudo -u postgres psql -X -tAc "SELECT 1 FROM pg_roles WHERE rolname='biopipeline'" | grep -qx 1; then
    sudo -u postgres createuser --pwprompt biopipeline
fi
if ! sudo -u postgres psql -X -tAc "SELECT 1 FROM pg_database WHERE datname='biopipeline2'" | grep -qx 1; then
    sudo -u postgres createdb --owner=biopipeline biopipeline2
fi
sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d biopipeline2 -c \
    'CREATE EXTENSION IF NOT EXISTS pgcrypto; CREATE EXTENSION IF NOT EXISTS pg_trgm;'
```

Keep the database password for section 7. Add an authentication rule scoped to
this database and role, before broader rules:

```bash
PG_HBA=$(sudo -u postgres psql -X -tAc 'SHOW hba_file')
PG_RULE='host biopipeline2 biopipeline 127.0.0.1/32 scram-sha-256'
if ! sudo grep -Fxq "$PG_RULE" "$PG_HBA"; then
    sudo cp -a "$PG_HBA" "${PG_HBA}.before-biopipeline2"
    sudo sed -i "1i $PG_RULE" "$PG_HBA"
    sudo systemctl reload postgresql
fi
psql -h 127.0.0.1 -U biopipeline -d biopipeline2 -W -c 'SELECT 1;'
```

Stop if this connection test fails. If reusing an old role whose password is
not SCRAM-compatible, reset only that role's password interactively with
`sudo -u postgres psql -X -c '\password biopipeline'`, then update section 7.

## 6. Service account, Git and backend installation

```bash
getent passwd biopipeline >/dev/null || sudo useradd --system \
    --home-dir /opt/biopipeline2 --shell /sbin/nologin biopipeline
sudo usermod -aG docker biopipeline
sudo install -d -o biopipeline -g biopipeline /opt/biopipeline2
sudo install -d -o root -g biopipeline -m 0750 /etc/biopipeline2
sudo install -d -o biopipeline -g biopipeline \
    /var/lib/biopipeline2/{artifacts,workspaces,environments,components}
if ! sudo test -d /opt/biopipeline2/.git; then
    sudo -u biopipeline git clone https://github.com/rpazuki/BioPipeline2.git /opt/biopipeline2
fi
cd /opt/biopipeline2
sudo -u biopipeline git log -1 --oneline
sudo -u biopipeline python3.12 -m venv .venv
sudo -u biopipeline .venv/bin/python -m pip install --upgrade pip
sudo -u biopipeline .venv/bin/python -m pip install ./backend
.venv/bin/uvicorn --version
.venv/bin/bp-create-admin --help
```

An existing checkout is not automatically updated. Select the intended release
before installing; the two executable checks must pass.

## 7. Application configuration

```bash
cd /opt/biopipeline2
if ! sudo test -f /etc/biopipeline2/biopipeline2.env; then
    sudo install -o root -g biopipeline -m 0640 deploy/biopipeline2.env.example \
        /etc/biopipeline2/biopipeline2.env
fi
python3.12 -c 'import secrets; print(secrets.token_urlsafe(48))'
sudoedit /etc/biopipeline2/biopipeline2.env
```

Set `BP_SESSION_SECRET` to the generated value and `BP_DATABASE_URL` to
`postgresql+psycopg://biopipeline:YOUR_PASSWORD@127.0.0.1:5432/biopipeline2`.
URL-encode special characters in the database password. Keep
`BP_ENVIRONMENT=production`, `BP_BASE_PATH=` and
`BP_TASK_DEFAULT_IMAGE=biopipeline2/task-base:1.0`. Adjust CPU/memory budgets
below the server's capacity. Leave the four storage roots under `/var/lib/biopipeline2`.

## 8. SELinux and task image

```bash
if [ "$(getenforce)" != "Disabled" ]; then
    if ! sudo semanage fcontext -a -t container_file_t '/var/lib/biopipeline2(/.*)?'; then
        sudo semanage fcontext -m -t container_file_t '/var/lib/biopipeline2(/.*)?'
    fi
    sudo restorecon -RF /var/lib/biopipeline2
fi
cd /opt/biopipeline2
sudo -u biopipeline docker info
sudo -u biopipeline docker build -f deploy/images/task/Dockerfile -t biopipeline2/task-base:1.0 .
sudo -u biopipeline docker run --rm \
    --user "$(id -u biopipeline):$(id -g biopipeline)" \
    -v /var/lib/biopipeline2/workspaces:/work:rw biopipeline2/task-base:1.0 \
    sh -c 'touch /work/.installation-check && rm /work/.installation-check'
```

Keep SELinux enabled. Label any additional container-mounted science-library
paths appropriately as well; do not recursively relabel unrelated shared storage.

## 9. Migrate and create the administrator

One-off commands must load the same environment file as the services:

```bash
sudo systemd-run --wait --pipe --collect --uid=biopipeline \
    --property=EnvironmentFile=/etc/biopipeline2/biopipeline2.env \
    --working-directory=/opt/biopipeline2/backend \
    /opt/biopipeline2/.venv/bin/alembic upgrade head
sudo systemd-run --wait --pty --collect --uid=biopipeline \
    --property=EnvironmentFile=/etc/biopipeline2/biopipeline2.env \
    --working-directory=/opt/biopipeline2 \
    /opt/biopipeline2/.venv/bin/bp-create-admin --email YOUR_EMAIL_ADDRESS
```

Replace the email placeholder. The administrator password is prompted twice
without echo. Repeating bootstrap leaves an existing active administrator unchanged.
Do not use the development seed script for production.

## 10. Build, start and wait for readiness

```bash
cd /opt/biopipeline2/frontend
sudo -u biopipeline npm ci
sudo -u biopipeline env NEXT_TELEMETRY_DISABLED=1 npm run build
if [ -d public ]; then
    sudo -u biopipeline cp -a public .next/standalone/
fi
sudo -u biopipeline cp -a .next/static .next/standalone/.next/

cd /opt/biopipeline2
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo install -d /etc/systemd/system/biopipeline2-frontend.service.d
printf '[Service]\nEnvironment=NEXT_TELEMETRY_DISABLED=1\n' |
    sudo tee /etc/systemd/system/biopipeline2-frontend.service.d/telemetry.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now biopipeline2-api biopipeline2-frontend \
    biopipeline2-scheduler biopipeline2-reaper biopipeline2-courier \
    biopipeline2-worker@1 biopipeline2-reconcile.timer

# enable --now does not restart an already-running service after edits.
sudo systemctl restart biopipeline2-api biopipeline2-frontend

# Starting a service is asynchronous: wait up to 60 seconds for readiness.
if ! curl --fail --silent --show-error --retry 30 --retry-delay 2 \
    --retry-connrefused --retry-max-time 60 http://127.0.0.1:8000/ready; then
    sudo systemctl --no-pager --full status biopipeline2-api || true
    sudo journalctl -u biopipeline2-api -b -n 100 --no-pager
    echo 'STOP: diagnose the API before configuring nginx.'
else
    curl -fsS http://127.0.0.1:8000/health
    curl -fsS -o /dev/null http://127.0.0.1:3000/login
fi
```

`public` is optional and currently absent from the repository. The conditional
skips it; copying `.next/static` is still required.


### Messages seen during section 10

- **`npm warn deprecated eslint@9.39.5`:** this pinned development linter is
  end-of-life. The warning alone does not fail `npm ci` or start/stop the Python
  API. Continue only if the install/build commands exit successfully. A maintained
  ESLint version should be upgraded and tested with `eslint-config-next` in the
  repository, including its lockfile; do not run an untested major upgrade or
  `npm audit fix --force` on the deployment host. See [ESLint version support](https://eslint.org/version-support/).
- **Next.js telemetry notice:** informational, not a build failure. The build
  environment and systemd override above disable it. See [Next.js telemetry](https://nextjs.org/telemetry).
- **`curl: (7) ... port 8000 ... Connection refused`:** no API listener was
  reachable at that moment. It can be startup delay or a failed/crashing service;
  the message alone does not identify the cause. Use the readiness wait above,
  then the diagnostics below. Opening the public firewall port or changing nginx
  will not fix a missing listener on localhost:8000.

### Diagnose a persistent API startup failure

```bash
sudo systemctl --no-pager --full status biopipeline2-api
sudo journalctl -u biopipeline2-api -b -n 100 --no-pager
sudo systemctl cat biopipeline2-api
sudo ss -lntp | grep ':8000' || true
sudo -u biopipeline test -r /etc/biopipeline2/biopipeline2.env
sudo -u biopipeline /opt/biopipeline2/.venv/bin/uvicorn --version
sudo -u biopipeline /opt/biopipeline2/.venv/bin/python -m pip check
```

Apply the fix matching the journal, rather than guessing:

| Journal symptom | Fix |
| --- | --- |
| `203/EXEC`, missing `uvicorn`, or `No module named ...` | Confirm the executable path and Git revision; reinstall the backend with the commands below. |
| Missing/unreadable environment file or unsafe production configuration | Correct section 7, replace placeholder secrets, and retain secure cookies/CSRF protection. |
| `226/NAMESPACE`, missing `ReadWritePaths`, or storage permissions | Create all four section 6 storage directories with the service account as owner; inspect custom unit overrides. |
| Database connection/authentication or missing-table errors | Repeat the section 5 connection check, verify the configured URL, and complete section 9 migrations. |
| `Address already in use` | Inspect `ss`; resolve the existing listener before starting this API. |
| SELinux denial | Inspect `sudo ausearch -m AVC -ts recent`; correct the specific path label/policy without disabling SELinux. |

For an older checkout or missing runtime dependency, select the corrected Git
revision, then reinstall (an existing checkout is not updated by `git clone`):

```bash
cd /opt/biopipeline2
# Review/select the intended corrected release first; do not overwrite local changes.
sudo -u biopipeline git status --short
sudo -u biopipeline git log -1 --oneline
sudo -u biopipeline .venv/bin/python -m pip install ./backend
sudo -u biopipeline .venv/bin/uvicorn --version
sudo systemctl daemon-reload
sudo systemctl reset-failed biopipeline2-api
sudo systemctl restart biopipeline2-api
curl --fail --silent --show-error --retry 30 --retry-delay 2 \
    --retry-connrefused --retry-max-time 60 http://127.0.0.1:8000/ready
```

If this still fails, the journal output is required to identify the actual
server-specific fix. Redact credentials before sharing logs or configuration.

## 11. nginx, HTTPS and an alternate public port

Port 80 is not required. This example uses **8443**; use 443 if it is free.
Do not change internal API/frontend ports just because port 80 is occupied.
Use a hostname resolving to this server and an institution-issued TLS certificate.

```bash
command -v nginx >/dev/null 2>&1 || sudo dnf install -y nginx
export BP_DOMAIN='biopipeline.your-institute.org'
export BP_PUBLIC_PORT=8443
export BP_TLS_CERT='/etc/pki/tls/certs/biopipeline.crt'
export BP_TLS_KEY='/etc/pki/tls/private/biopipeline.key'
sudo test -s "$BP_TLS_CERT"
sudo test -s "$BP_TLS_KEY"
sudo ss -lntp | grep ":${BP_PUBLIC_PORT}" || true
```

Install the certificate/key at the chosen paths before continuing. If this
site file already exists, review/edit it instead of overwriting it:

```bash
sudo test ! -e /etc/nginx/conf.d/biopipeline2.conf &&
sudo tee /etc/nginx/conf.d/biopipeline2.conf >/dev/null <<EOF_NGINX
server {
    listen ${BP_PUBLIC_PORT} ssl;
    server_name ${BP_DOMAIN};
    ssl_certificate ${BP_TLS_CERT};
    ssl_certificate_key ${BP_TLS_KEY};
    client_max_body_size 128m;
    proxy_request_buffering off;
    location = /health { proxy_pass http://127.0.0.1:8000; }
    location = /ready { proxy_pass http://127.0.0.1:8000; }
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 1800s;
    }
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF_NGINX

if [ "$(getenforce)" != "Disabled" ]; then
    sudo restorecon -v "$BP_TLS_CERT" "$BP_TLS_KEY"
    sudo setsebool -P httpd_can_network_connect 1
    # Inspect first; 8443 is commonly already assigned to http_port_t.
    sudo semanage port -l | grep '^http_port_t'
fi
```

If the chosen port is absent from `http_port_t`, add it with
`sudo semanage port -a -t http_port_t -p tcp "$BP_PUBLIC_PORT"`.
If it belongs to another SELinux type, review that service before changing it.
Red Hat documents the reverse-proxy boolean in its [nginx guide](https://docs.redhat.com/documentation/red_hat_enterprise_linux/10/html/deploying_web_servers_and_reverse_proxies/setting-up-and-configuring-nginx).

RHEL's default nginx configuration may itself listen on port 80. If another
server owns port 80, inspect `sudo nginx -T` and edit only the unused default
server block in `/etc/nginx/nginx.conf` to remove that listener. Preserve other
sites. Adding an 8443 site alone does not remove the default listener.

```bash
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
if sudo systemctl is-active --quiet firewalld; then
    sudo firewall-cmd --permanent --add-port="${BP_PUBLIC_PORT}/tcp"
    sudo firewall-cmd --reload
fi
```

Keep 8000, 3000 and 5432 private. If the host uses a different firewall or
upstream access controls, allow the chosen public port there as well.

## 12. Final verification

```bash
curl -fsS "https://${BP_DOMAIN}:${BP_PUBLIC_PORT}/health"
curl -fsS "https://${BP_DOMAIN}:${BP_PUBLIC_PORT}/ready"
sudo systemctl --no-pager status biopipeline2-api biopipeline2-frontend biopipeline2-worker@1
sudo journalctl -u biopipeline2-api -u biopipeline2-worker@1 -n 80 --no-pager
```

Open `https://YOUR_HOSTNAME:8443`, sign in and test a small pipeline through
submission, execution and download. If public checks fail while local readiness
passes, inspect nginx, DNS, TLS and firewall configuration separately.

Related: [deployment](operations/deployment.md), [upgrades](operations/upgrades.md),
and [backup/restore](operations/backup-and-restore.md).

## Deployment follow-up: certificate trust and wrong application (2026-10-18)

On `rlalab-assist.dept.ic.ac.uk`, local API readiness passed all checks.
The externally served TLS chain contained the hostname certificate and Imperial
College Subordinate Certificate Authority 2020. Client verification failed at
that intermediate because Imperial's private root was not trusted. The user
wants to avoid per-user trust installation. Pending resolution: obtain a publicly
trusted hostname certificate or use a trusted institutional reverse proxy/Zscaler
Browser Access endpoint through ICT. Other certificates inspected were Imperial's
private root and OSADMIN CA, not publicly trusted hostname alternatives.

A later browser visit to `/login` showed another application. A successful HTTP
200 alone does not establish that the responding frontend is BioPipeline.
Check for a port-3000 collision before changing anything:

```bash
sudo ss -lntp | grep -E ':(3000|3100|8443)\b' || true
sudo systemctl --no-pager --full status biopipeline2-frontend
sudo journalctl -u biopipeline2-frontend -b -n 60 --no-pager
sudo nginx -T 2>&1 | grep -nE 'configuration file|listen|server_name|proxy_pass'
```

If another application owns 3000, preserve it. Choose a free port (for example
3100), override only BioPipeline's frontend port, and update only the BioPipeline
nginx server block's frontend `proxy_pass` to `http://127.0.0.1:3100;`. Leave the
API proxy on 8000. If that port is free:

```bash
sudo install -d /etc/systemd/system/biopipeline2-frontend.service.d
printf '[Service]\nEnvironment=PORT=3100\n' |
    sudo tee /etc/systemd/system/biopipeline2-frontend.service.d/port.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart biopipeline2-frontend
curl --noproxy '*' -fsS http://127.0.0.1:3100/login
sudoedit /etc/nginx/conf.d/biopipeline2.conf
# In this site's location / only: proxy_pass http://127.0.0.1:3100;
sudo nginx -t && sudo systemctl reload nginx
```

If 3000 already belongs to BioPipeline, inspect duplicate nginx `server_name`
blocks and the active virtual host instead of assuming a port collision.

### Alembic fails with invalid interpolation syntax

A URL-encoded password (for example `%40` for `@`) must stay URL-encoded in
`BP_DATABASE_URL`. Older revisions passed percent signs unescaped into Alembic's
ConfigParser. In `backend/alembic/env.py`, use:

```python
config.set_main_option("sqlalchemy.url", str(load_settings().database_url).replace("%", "%%"))
```

The doubling applies only inside the Alembic loader, not the environment file.
Update the server checkout with this fix, rerun section 9 migrations, then create
the administrator. No API restart is required for this migration-loader change.

## Updating an existing installation from Git

Follow [Updating BioPipeline2 from Git](operations/upgrades.md) for routine
updates and database migrations. Pulling source alone does not update installed
Python packages or the frontend production build. The guide includes draining
workers, backups, migration checks, rebuilds, service startup and rollback.
It preserves the frontend port override and the existing nginx/TLS configuration.

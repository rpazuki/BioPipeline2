# Installing BioPipeline2 on a clean Linux VM

Written to be followed top to bottom on a machine with nothing on it. If a
step here does not work on a fresh Ubuntu 24.04 host, that is a bug in this
document, not in your machine — the acceptance criterion for Phase 9 is that
this file is sufficient.

Everything is one VM. That is a decision, not a limitation of the code: five
to twenty users, tasks that range from seconds to days, and a laboratory that
has to be able to look after it (ADR 0006). PostgreSQL, the API, the frontend
and the workers all live here.

## What you are installing

| Process | What it does | If it stops |
| --- | --- | --- |
| `postgres` | The system of record | Everything stops |
| `biopipeline2-api` | HTTP API | Nobody can submit or read anything; running tasks continue |
| `biopipeline2-frontend` | The Next.js server | The browser sees nothing; the API still works |
| `biopipeline2-worker@N` | Claims and runs tasks in containers | Queued work waits; leases expire and are requeued |
| `biopipeline2-scheduler` | Creates the runs schedules are due | Scheduled runs silently do not happen |
| `biopipeline2-reaper` | Expired leases, cancellations, retention | Failures stop converging and the disk stops being reclaimed |
| `biopipeline2-courier` | Copies outputs to shared storage | Deliveries queue up; nothing is lost |

The worker is the only one that needs the container runtime, and the only one
whose stop must be allowed to take hours.

## 1. Packages

```bash
sudo apt update
sudo apt install -y python3.13 python3.13-venv postgresql-16 nginx docker.io nodejs npm rsync
sudo systemctl enable --now postgresql docker
```

Node 22 or newer is required; check with `node --version` and install from
NodeSource if the distribution's is older.

## 2. Account and directories

```bash
sudo useradd --system --home /opt/biopipeline2 --shell /usr/sbin/nologin biopipeline
sudo usermod -aG docker biopipeline
sudo mkdir -p /opt/biopipeline2 /etc/biopipeline2
sudo mkdir -p /var/lib/biopipeline2/{artifacts,workspaces,environments,components}
sudo chown -R biopipeline:biopipeline /opt/biopipeline2 /var/lib/biopipeline2
```

Put `/var/lib/biopipeline2` on the volume you are prepared to fill. Outputs,
workspaces and environment builds all live there, and a full artifact root
fails every promotion — which fails every run that produced one.

Being in the `docker` group is root-equivalent on this host. It is what lets a
worker run a task container, and it is the reason the worker runs as its own
unprivileged account and nothing else joins that group.

## 3. The code

```bash
sudo -u biopipeline git clone <this repository> /opt/biopipeline2
cd /opt/biopipeline2
sudo -u biopipeline python3.13 -m venv .venv
sudo -u biopipeline .venv/bin/pip install --upgrade pip
sudo -u biopipeline .venv/bin/pip install ./backend
```

## 4. Database

```bash
sudo -u postgres createuser biopipeline --pwprompt
sudo -u postgres createdb biopipeline2 --owner biopipeline
```

The schema needs `pgcrypto` for `gen_random_uuid()`; the first migration
creates the extension, which requires the database owner to be a superuser
**or** the extension to be installed once by hand:

```bash
sudo -u postgres psql -d biopipeline2 -c 'CREATE EXTENSION IF NOT EXISTS pgcrypto'
```

## 5. Configuration

```bash
sudo cp /opt/biopipeline2/deploy/biopipeline2.env.example /etc/biopipeline2/biopipeline2.env
sudo chown root:biopipeline /etc/biopipeline2/biopipeline2.env
sudo chmod 640 /etc/biopipeline2/biopipeline2.env
sudoedit /etc/biopipeline2/biopipeline2.env
```

Read that file: every setting in it is one a deployment has to decide. The
session secret and the database password are the two that must not be left as
they are — and the API refuses to boot in production with the development
secret, deliberately, rather than serving with it.

## 6. The task image

Every task runs in this image, and so does every environment build. It is
built from the repository:

```bash
cd /opt/biopipeline2
sudo -u biopipeline docker build -f deploy/images/task/Dockerfile -t biopipeline2/task-base:1.0 .
```

Tag it with a version and put that tag in the configuration. `latest` makes a
run's record of the image it used meaningless.

## 7. Migrate, and make the first administrator

```bash
cd /opt/biopipeline2/backend
sudo -u biopipeline --preserve-env=BP_DATABASE_URL ../.venv/bin/alembic upgrade head
```

Then one account, with a password you choose and hand over out of band:

```bash
cd /opt/biopipeline2
sudo -u biopipeline BP_SEED_ADMIN_EMAIL=you@your-lab.org \
  BP_SEED_ADMIN_PASSWORD='...' .venv/bin/python scripts/dev/seed.py
```

The script refuses to invent a password: a seeded account with a well-known
one is a back door that outlives the afternoon it was convenient for, and this
one is an administrator. Every later account is created from the Admin screen,
which generates a one-time password and forces its replacement at first
sign-in.

## 8. Build the frontend

```bash
cd /opt/biopipeline2/frontend
sudo -u biopipeline npm ci
sudo -u biopipeline npm run build
sudo -u biopipeline cp -r public .next/standalone/public
sudo -u biopipeline cp -r .next/static .next/standalone/.next/static
```

The last two lines are not optional: a standalone Next build emits a server
bundle without the static assets beside it.

If the platform is mounted under a path prefix, set `NEXT_PUBLIC_BASE_PATH`
**at build time** to the same value as `BP_BASE_PATH`. Next bakes it into
every asset URL, so it cannot be changed afterwards without rebuilding.

## 9. Services

```bash
sudo cp /opt/biopipeline2/deploy/systemd/*.service /opt/biopipeline2/deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now biopipeline2-api biopipeline2-frontend \
  biopipeline2-scheduler biopipeline2-reaper biopipeline2-courier
sudo systemctl enable --now biopipeline2-worker@1
sudo systemctl enable --now biopipeline2-reconcile.timer
```

Run one worker per parallel task you want the host to attempt, and set the
admission budget below the machine's real capacity. Two workers with a budget
sized for one host will not oversubscribe it — the budget is per host, not per
worker — but they will each hold an idle database connection, so start with
one and add another when the queue says so.

## 10. nginx

```nginx
server {
    listen 443 ssl;
    server_name biopipeline.your-lab.org;

    ssl_certificate     /etc/letsencrypt/live/biopipeline.your-lab.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/biopipeline.your-lab.org/privkey.pem;

    # Inputs are multi-gigabyte and arrive in chunks. The limit has to clear
    # one chunk (BP_UPLOAD_CHUNK_MAX_BYTES, 64 MiB by default), not one file.
    client_max_body_size 128m;
    # Stream chunks through rather than spooling each one to disk first.
    proxy_request_buffering off;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # A publish or an install can take minutes; a build that compiles a
        # wheel can take many.
        proxy_read_timeout 1800s;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

TLS is not optional: session cookies are issued with `Secure` in production,
so over plain HTTP nobody can stay signed in.

## 11. Check it

```bash
curl -fsS https://biopipeline.your-lab.org/api/v1/health
curl -fsS https://biopipeline.your-lab.org/api/v1/ready
```

`/health` says the process is up and touches nothing. `/ready` answers whether
it can actually serve: the database, and each storage root. A `degraded`
answer names which one, and the usual cause is a root that exists in the
configuration and not on disk.

Then, in a browser: sign in, create an environment, install one package, write
a one-stage pipeline, publish it, submit it, and download what it produced. If
each of those works, the deployment works; the Admin screen's **Right now**
panel is where you watch it afterwards (see [monitoring.md](monitoring.md)).

## When it does not work

**`/ready` says a root is missing.** The directory does not exist or the
`biopipeline` account cannot read it. The units confine every process to
`/var/lib/biopipeline2`; a root outside it must also be added to that unit's
`ReadWritePaths`, or systemd will refuse the write and the error will look
like a permission problem in the application.

**Tasks stay queued.** Either no worker is running (`systemctl status
'biopipeline2-worker@*'`) or every task requests more than the admission
budget allows. The budget is the second thing to check and the first thing
people forget.

**A task fails immediately with an image error.** The worker pulls nothing: the
image must exist locally, on the host that runs the worker.

**The frontend loads but every request fails.** Almost always the path prefix:
`BP_BASE_PATH` and the `NEXT_PUBLIC_BASE_PATH` the frontend was *built* with
have to agree.

**An environment install fails with a permission error.** The `biopipeline`
account is not in the `docker` group, or the group was added after the worker
started — group membership is read at process start.

## Related

- [backup-and-restore.md](backup-and-restore.md) — what to copy, in which order, and how to prove it worked.
- [upgrades.md](upgrades.md) — draining, migrating, and going back.
- [monitoring.md](monitoring.md) — the numbers worth an alert, and their thresholds.

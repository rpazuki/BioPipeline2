# Upgrading, and going back

The constraint that shapes this whole procedure: **a task can run for days.**
An upgrade that kills a worker throws away work somebody has been waiting for
since Tuesday, and no amount of retry logic makes that acceptable when it was
avoidable.

So a worker is never killed. It is asked to stop claiming, and it leaves when
the task in hand is finished.

## Before you start

- Take a backup ([backup-and-restore.md](backup-and-restore.md)). The database
  part is thirty seconds and it is the only thing standing between a bad
  migration and a bad week.
- Look at the Admin screen's **Right now** panel. Upgrading while a hundred
  tasks are queued means a long drain; upgrading while the queue is empty is
  minutes.
- Read the release's migrations. `alembic history` shows what will run, and a
  migration that drops a column is one to think about before, not during.

## The order

```bash
# 1. New code, without restarting anything.
cd /opt/biopipeline2
sudo -u biopipeline git fetch && sudo -u biopipeline git checkout <tag>
sudo -u biopipeline .venv/bin/pip install ./backend
cd frontend && sudo -u biopipeline npm ci && sudo -u biopipeline npm run build
sudo -u biopipeline cp -r public .next/standalone/public
sudo -u biopipeline cp -r .next/static .next/standalone/.next/static

# 2. Drain the workers. This blocks until each finishes what it holds; the
#    unit allows twelve hours by default. The Admin screen shows them as
#    `draining` while they work, which is the difference between a worker
#    that is busy and one that is leaving.
sudo systemctl stop 'biopipeline2-worker@*'

# 3. Migrate. Nothing is claiming now, so the schema moves under no one.
cd /opt/biopipeline2/backend
sudo -u biopipeline --preserve-env=BP_DATABASE_URL ../.venv/bin/alembic upgrade head

# 4. Restart the rest, then the workers.
sudo systemctl restart biopipeline2-api biopipeline2-frontend \
  biopipeline2-scheduler biopipeline2-reaper biopipeline2-courier
sudo systemctl start biopipeline2-worker@1
```

Between steps 2 and 4 the platform is readable and submittable; nothing
executes. Queued work simply waits, which is what a queue is for.

## If a task must survive the upgrade

A run that has been going for two days and must not be restarted changes only
one thing: do not stop its worker at all. Drain the *other* workers, upgrade,
and let the last one finish in its own time — it goes on running the code it
started with, and the generation it pinned is still exactly where it was
because nothing ever mutates one (ADR 0028).

What that costs you is a window where one worker runs old code against a new
schema. It is safe only for an additive migration: a new column, a new table,
a new index. A migration that removes or renames something the running code
still uses will fail that worker's next write. When a release contains one,
drain everything.

## Going back

Prefer rolling forward. A fix released ten minutes later is almost always
cheaper than a downgrade, because a downgrade has to undo data as well as
schema.

When you do have to go back:

```bash
sudo systemctl stop 'biopipeline2-worker@*' biopipeline2-scheduler \
  biopipeline2-reaper biopipeline2-courier biopipeline2-api

cd /opt/biopipeline2/backend
sudo -u biopipeline --preserve-env=BP_DATABASE_URL ../.venv/bin/alembic downgrade <revision>

cd /opt/biopipeline2
sudo -u biopipeline git checkout <previous tag>
sudo -u biopipeline .venv/bin/pip install ./backend
# rebuild the frontend as in step 1, then start everything again
```

Every migration in this repository has a `downgrade`, and they are exercised.
That makes the *schema* reversible; it does not make the data reversible. A
downgrade that drops a column drops what was in it, and no backup taken after
the upgrade contains it either. If the data matters, restore the pre-upgrade
dump instead of downgrading.

## Afterwards

```bash
curl -fsS https://<host>/api/v1/ready
sudo -u biopipeline /opt/biopipeline2/.venv/bin/python /opt/biopipeline2/scripts/ops/reconcile.py
```

Then watch the queue drain for a few minutes. The failure that shows up after
an upgrade and nowhere else is a task that starts and immediately fails,
usually because the task image tag moved or an environment generation was
reclaimed while nothing was looking.

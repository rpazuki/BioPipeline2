# Backup and restore

A backup nobody has restored is a hypothesis. This document is written so the
restore can be rehearsed on a spare VM in an afternoon, and it ends with the
check that says whether it worked.

Backup and restore are an **operator procedure**, not a button in the
application. Whether the platform should also offer one is
[ADR 0021](../../migration/docs/adr/0021-in-app-backup-restore-scope.md), which
is still open; nothing here waits on that decision.

## What to copy, and what not to

| Path | Why |
| --- | --- |
| The database | The system of record. Everything else can be re-derived or is replaceable; this cannot. |
| `/var/lib/biopipeline2/artifacts` | The bytes people download. A row without them is the one failure that matters. |
| `/etc/biopipeline2/biopipeline2.env` | The session secret and the database password. Store it where secrets go, not beside the dumps. |
| `/var/lib/biopipeline2/components` | Component libraries a pipeline may reference. Small, and a pipeline that names a missing one will not compile. |
| `/var/lib/biopipeline2/environments` | Optional. Each generation is reproducible from its recorded package list *unless* it contains an editable install — those cannot be rebuilt, because they are links to a working tree. |
| `/var/lib/biopipeline2/workspaces` | **No.** Scratch space; a workspace is never the record of anything (ADR 0012). |

## The order is the whole trick

**Database first. Artifacts second.**

A dump taken at `T0` names only bytes that existed at `T0`. Copying the
artifact tree afterwards therefore captures everything the dump refers to, and
usually some extra — files promoted while the copy was running, which no
restored row mentions. Those extras are *orphans*: disk, and nothing else.

The other order produces the failure that matters. Artifacts copied first,
database dumped second, and every artifact promoted in between is a row whose
bytes were never copied. Somebody clicks a download and it is gone.

This is the same rule the platform follows everywhere: bytes before the row
that promises them.

## Taking one

```bash
#!/bin/bash
set -euo pipefail
stamp=$(date -u +%Y%m%dT%H%M%SZ)
dest=/backup/biopipeline2/$stamp
mkdir -p "$dest"

# 1. The database, first, and as a custom-format dump so it can be restored
#    selectively and in parallel.
sudo -u postgres pg_dump -Fc -d biopipeline2 -f "$dest/biopipeline2.dump"

# 2. The bytes, second. No --delete: this is an archive, not a mirror, and a
#    file removed by the janitor is not a reason to remove it from history.
rsync -a --link-dest=/backup/biopipeline2/latest/artifacts/ \
  /var/lib/biopipeline2/artifacts/ "$dest/artifacts/"
rsync -a /var/lib/biopipeline2/components/ "$dest/components/"

ln -sfn "$dest" /backup/biopipeline2/latest
```

`--link-dest` hardlinks unchanged files against the previous run, so a daily
backup of a terabyte of outputs costs the day's new outputs rather than a
terabyte. It works because artifacts are immutable once promoted — nothing in
this system rewrites a stored file in place.

Run it from a systemd timer, and put the destination on a different machine or
at least a different volume. A backup on the disk that fills up is not one.

## Restoring

Stop everything that writes first. A restore into a live deployment gives you
a database describing one moment and disks describing another.

```bash
sudo systemctl stop biopipeline2-worker@* biopipeline2-scheduler \
  biopipeline2-reaper biopipeline2-courier biopipeline2-api

# The workers may take a while: they drain rather than dying, which is the
# behaviour you want every other day of the year.

sudo -u postgres dropdb --if-exists biopipeline2
sudo -u postgres createdb biopipeline2 --owner biopipeline
sudo -u postgres psql -d biopipeline2 -c 'CREATE EXTENSION IF NOT EXISTS pgcrypto'
sudo -u postgres pg_restore -d biopipeline2 --no-owner --role=biopipeline \
  /backup/biopipeline2/<stamp>/biopipeline2.dump

sudo -u biopipeline rsync -a /backup/biopipeline2/<stamp>/artifacts/ \
  /var/lib/biopipeline2/artifacts/

# If the code is newer than the dump, bring the schema forward before anything
# connects to it.
cd /opt/biopipeline2/backend
sudo -u biopipeline --preserve-env=BP_DATABASE_URL ../.venv/bin/alembic upgrade head

sudo systemctl start biopipeline2-api biopipeline2-scheduler \
  biopipeline2-reaper biopipeline2-courier biopipeline2-worker@1
```

### What a restore does to work that was in flight

- **Tasks that were running** have leases the reaper will find expired. They
  are requeued and run again. A task is expected to be safely re-runnable;
  this is when that expectation is collected on.
- **Runs that finished after the dump** are gone from the record. Their
  outputs may still be on disk, as orphans, and are no longer reachable.
- **Uploads in progress** are gone. The client is told the offset does not
  match and starts again.
- **Workers** re-register themselves. The rows describing the old ones are
  whatever the dump held; the reaper marks the absent ones stopped.

## Proving it worked

```bash
sudo -u biopipeline /opt/biopipeline2/.venv/bin/python \
  /opt/biopipeline2/scripts/ops/reconcile.py
```

It compares every table that names a path against the paths it names, and
exits **1** if any row promises bytes that are not there. That is the Phase 9
acceptance criterion, and it is the only statement worth trusting about a
restore.

Expect it to report **orphans** — directories nothing points at. A
database-first backup produces them by design, and a restore of an older
database produces more. They are disk, not damage. Reclaim them once you are
satisfied the restore is the one you meant to keep:

```bash
sudo -u biopipeline /opt/biopipeline2/.venv/bin/python \
  /opt/biopipeline2/scripts/ops/reconcile.py --reclaim
```

`--reclaim` removes directories and writes nothing to the database. An
operator freeing disk should not also be rewriting the record of what
happened.

## Rehearse it

Once a quarter, restore the most recent backup onto a spare VM and run the
reconciliation there. The failures this finds are never the ones anybody
predicted: a missing `pgcrypto`, an artifact volume that was never in the
backup script, a secret file nobody copied and no session that survives
without it.

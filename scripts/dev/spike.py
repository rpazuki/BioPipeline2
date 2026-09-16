#!/usr/bin/env python3
"""Phase 0b: run a real-shaped pipeline all the way through the platform.

The roadmap's rule is to prove the riskiest assumptions first, and this is the
assumption everything else rests on: that a pipeline of the shape the lab
actually writes can be compiled, fanned out, materialised, claimed, executed
in a container, verified and promoted — without anybody editing the platform
to make one particular document work.

It is a script rather than a test because it needs Docker, a database and a
few hundred milliseconds per container, and because its output is meant to be
read by a person deciding whether the design holds.

See `examples/spike/README.md` for exactly what this does and does not prove.
The short version: the pipeline, the compiler, the fan-out, the contract, the
container and the promotion are real; `labUtils` is a standard-library
stand-in with the real call shapes, and there is no reference run to compare
scientific output against.

    make db-up && make migrate && make task-image
    make spike
"""

from __future__ import annotations

import pathlib
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import yaml
from app.application.pipelines import create_revision
from app.application.runs import submit_run
from app.infrastructure.execution.docker import DockerAdapter
from app.infrastructure.fanout import DirectoryFanOut
from app.infrastructure.pipeline_loader import DirectoryLibraryLoader
from app.settings import load_settings
from app.workers.worker import Worker
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

PIPELINE = ROOT / "examples/pipelines/od600_growth_rates.yaml"
COMPONENTS = ROOT / "examples/components"
STAND_IN = ROOT / "examples/spike/stand_in"

WELLS = ("A1", "A2", "B1", "B2")
PLATES = ("plate_01", "plate_02", "plate_03")


def say(message: str) -> None:
    print(f"\n\033[1m{message}\033[0m", flush=True)


def make_data(root: pathlib.Path) -> pathlib.Path:
    """Three plate-reader exports, their metadata, and a mapping file.

    Synthetic, and deliberately simple: a growth curve whose maximum slope can
    be worked out by hand, so a wrong answer is visible rather than plausible.
    """
    root.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for index, plate in enumerate(PLATES, start=1):
        rows = ["well,time_h,od600"]
        for well_index, well in enumerate(WELLS):
            for hour in range(8):
                # Doubling every two hours, offset per well and per plate so no
                # two series are identical.
                od = 0.05 * (2 ** (hour / 2)) * (1 + 0.1 * well_index) * index
                rows.append(f"{well},{hour},{od:.6f}")
        (root / f"{plate}.csv").write_text("\n".join(rows) + "\n")

        meta = ["well,group_id"] + [f"{well},{well[0]}" for well in WELLS]
        (root / f"{plate}_meta.csv").write_text("\n".join(meta) + "\n")
        mapping[f"{plate}.csv"] = f"{plate}_meta.csv"

    mapping_file = root / "mapping.yaml"
    mapping_file.write_text(yaml.safe_dump(mapping, sort_keys=True))
    return mapping_file


def attest_root(session: Session, path: pathlib.Path) -> str:
    """Register the data directory as an attested shared-storage root.

    Attested because ADR 0013 makes that the basis on which the platform may
    read shared storage at all, and the database refuses to hold a
    service-account root without one.
    """
    project_id = session.execute(
        text("SELECT id FROM projects WHERE is_default")
    ).scalar_one()
    admin_id = session.execute(
        text(
            "INSERT INTO users (email, display_name, role) VALUES (:e, 'Spike', 'admin') "
            "RETURNING id"
        ),
        {"e": f"spike-{uuid.uuid4().hex[:8]}@example.org"},
    ).scalar_one()
    root_id = f"spike_{uuid.uuid4().hex[:8]}"
    session.execute(
        text(
            "INSERT INTO shared_storage_roots "
            "(id, project_id, label, root_path, readable, writable, identity_mode, "
            " attested_by, attested_at, attestation_note) "
            "VALUES (:id, :p, 'Spike data', :path, true, false, 'service_account', "
            "        :by, now(), 'Synthetic data created by scripts/dev/spike.py')"
        ),
        {"id": root_id, "p": project_id, "path": str(path), "by": admin_id},
    )
    return str(admin_id)


def main() -> int:
    settings = load_settings(
        component_library_root=COMPONENTS,
        task_library_paths=[STAND_IN],
        artifact_root=ROOT / ".artifacts",
        workspace_root=ROOT / ".workspaces",
    )
    settings.artifact_root.mkdir(parents=True, exist_ok=True)
    settings.workspace_root.mkdir(parents=True, exist_ok=True)

    adapter = DockerAdapter(
        image=settings.task_default_image,
        binary=settings.container_runtime,
        library_paths=(str(STAND_IN),),
    )
    if not adapter.available():
        print(
            "spike: no container runtime; run `make task-image` first", file=sys.stderr
        )
        return 2

    data_root = ROOT / ".spike" / uuid.uuid4().hex[:8]
    mapping_file = make_data(data_root)
    say(f"1. data: {len(PLATES)} plates x {len(WELLS)} wells under {data_root}")

    engine = create_engine(str(settings.database_url))
    with Session(engine) as session:
        owner = attest_root(session, data_root)
        adapter.extra_mounts[str(data_root)] = str(data_root)

        say("2. compile and store an immutable revision")
        source = PIPELINE.read_text().replace(
            "pipeline: od600_growth_rates", f"pipeline: spike_{uuid.uuid4().hex[:6]}"
        )
        created = create_revision(
            session,
            source_text=source,
            owner_id=uuid.UUID(owner),
            load_library=DirectoryLibraryLoader(COMPONENTS),
        )
        session.commit()
        print(f"   revision {created.revision_id} v{created.version}")
        print(f"   graph    {created.graph_hash}")

        say("3. submit, fanning out over the mapping file")
        submitted = submit_run(
            session,
            pipeline_revision_id=created.revision_id,
            requested_by=uuid.UUID(owner),
            values={"data_root": str(data_root), "mapping_yaml": str(mapping_file)},
            enumerate_fanout=DirectoryFanOut((data_root,)),
        )
        session.commit()
        run_id = submitted.run_id
        print(f"   run {run_id} -> {submitted.task_count} tasks")
        for (key,) in session.execute(
            text("SELECT task_key FROM run_tasks WHERE run_id = :r ORDER BY task_key"),
            {"r": run_id},
        ):
            print(f"     {key}")

    say("4. execute every task in a container")
    worker = Worker(
        engine, settings, adapter=adapter, worker_id=f"spike-{uuid.uuid4().hex[:6]}"
    )
    # Bounded, so a task that never becomes claimable ends the spike rather
    # than hanging. The generous multiplier covers the idle cycles between a
    # task finishing and its dependants being released.
    started = time.monotonic()
    completed = worker.run_forever(max_iterations=submitted.task_count * 4 + 8)
    print(f"   {completed} task(s) executed in {time.monotonic() - started:.1f}s")

    say("5. what happened")
    with Session(engine) as session:
        status = session.execute(
            text("SELECT status FROM runs WHERE id = :r"), {"r": run_id}
        ).scalar_one()
        print(f"   run: {status}")
        for key, task_status, reason in session.execute(
            text(
                "SELECT task_key, status, status_reason FROM run_tasks "
                "WHERE run_id = :r ORDER BY task_key"
            ),
            {"r": run_id},
        ):
            print(f"     {task_status:<10} {key}{'  ' + reason if reason else ''}")

        rows = list(
            session.execute(
                text(
                    "SELECT kind, filename, size_bytes, substr(checksum_sha256, 1, 12) "
                    "FROM artifacts WHERE run_id = :r AND deleted_at IS NULL "
                    "ORDER BY filename"
                ),
                {"r": run_id},
            )
        )
        print(f"   artifacts: {len(rows)}")
        for kind, filename, size, digest in rows:
            print(f"     {kind:<12} {filename:<28} {size:>8}B  {digest}")

        for field, mode, delivery_status in session.execute(
            text(
                "SELECT field_key, mode, status FROM run_deliveries WHERE run_id = :r "
                "ORDER BY field_key, mode"
            ),
            {"r": run_id},
        ):
            print(f"   delivery: {field} via {mode} -> {delivery_status}")

    print()
    return 0 if status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())

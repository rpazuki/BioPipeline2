#!/usr/bin/env python3
"""Install the reviewed optical-density growth-rate workflows on a configured server."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.application.audit import RequestContext, record
from app.application.environments import (
    change_packages,
    current_generation,
    default_environment,
    packages_of,
)
from app.application.workflow_bundles import install_bundle
from app.infrastructure.db.models import User
from app.infrastructure.environments import GenerationBuilder
from app.infrastructure.execution.docker import host_user
from app.settings import load_settings


def prepare_environment(session, settings, actor_id):
    """Install the reviewed requirements in new generations and verify the configured runtime."""
    environment = default_environment(session)
    if environment is None:
        raise RuntimeError(
            "Configure a default execution environment before importing these workflows."
        )
    builder = GenerationBuilder(
        image=settings.task_default_image,
        root=settings.environment_root,
        binary=settings.container_runtime,
        timeout_seconds=settings.environment_build_timeout_seconds,
        run_as=settings.task_run_as or host_user(),
    )
    requirements = yaml.safe_load(
        (ROOT / "examples/migrations/od600/bundle.yaml").read_text()
    )["runtime_requirements"]
    for requirement in requirements:
        generation = current_generation(session, environment)
        if generation is None or generation.status != "ready":
            raise RuntimeError(
                "The default execution environment needs a ready generation."
            )
        name, version = requirement.split("==", 1)
        installed = {
            package.name.lower().replace("_", "-"): package.version
            for package in packages_of(generation)
        }
        if installed.get(name.lower()) == version:
            continue
        result = change_packages(
            session,
            environment,
            operation="install",
            specifier=requirement,
            builder=builder,
            actor_id=actor_id,
        )
        if not result.succeeded:
            raise RuntimeError(
                f"Installing {requirement} failed: {result.message}\n{result.log}"
            )
        record(
            session,
            action="environment.packages_changed",
            target_type="environment",
            target_id=environment.id,
            context=RequestContext(actor_id=actor_id),
            specifier=requirement,
        )
        session.commit()
        print(f"Prepared {requirement}", flush=True)
    generation = current_generation(session, environment)
    check = builder._run(
        Path(generation.generation_path), "/env/bin/python -m pip check", writable=False
    )
    if check.returncode:
        raise RuntimeError(check.stdout + check.stderr)
    paths = [str(path) for path in settings.task_library_paths]
    command = [
        settings.container_runtime,
        "run",
        "--rm",
        "--read-only",
        "--network",
        "none",
        "--user",
        settings.task_run_as or host_user(),
        "--tmpfs",
        "/tmp:rw,mode=1777",
        "--volume",
        f"{generation.generation_path}:/env:ro",
    ]
    for path in paths:
        command += ["--volume", f"{path}:{path}:ro"]
    command += [
        "--env",
        "PYTHONPATH=" + ":".join(["/env/lib/python3.12/site-packages", *paths]),
        "--env",
        "MPLBACKEND=Agg",
        "--env",
        "MPLCONFIGDIR=/tmp/matplotlib",
        settings.task_default_image,
        "python",
        "-c",
        "import labUtils.media_bot, labUtils.growth_rates, labUtils.utils, openpyxl; print('OD600 runtime imports passed')",
    ]
    checked = subprocess.run(
        command, capture_output=True, text=True, timeout=60, check=False
    )
    if checked.returncode:
        raise RuntimeError(
            "The configured task runtime cannot import the processing functions. "
            "Check BP_TASK_LIBRARY_PATHS.\n" + checked.stdout + checked.stderr
        )
    print(checked.stdout.strip(), flush=True)


def main() -> int:
    """Validate or install definitions using an existing administrator as the audit actor."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--admin-email", help="Required when more than one active administrator exists."
    )
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--prepare-environment", action="store_true")
    parser.add_argument(
        "--runtime-info",
        action="store_true",
        help="Print non-secret deployment paths and image name.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and roll back without installing.",
    )
    args = parser.parse_args()
    if args.check and args.prepare_environment:
        parser.error(
            "Use --check without --prepare-environment; checking does not install packages."
        )
    settings = load_settings()
    if args.runtime_info:
        print(
            json.dumps(
                {
                    "image": settings.task_default_image,
                    "library_paths": [
                        str(path) for path in settings.task_library_paths
                    ],
                    "component_root": str(settings.component_library_root),
                }
            )
        )
        return 0
    engine = create_engine(str(settings.database_url))
    with Session(engine) as session:
        query = select(User).where(User.role == "admin", User.is_active.is_(True))
        if args.admin_email:
            query = query.where(User.email == args.admin_email)
        administrators = list(session.scalars(query))
        if len(administrators) != 1:
            parser.error(
                "Select one active administrator with --admin-email; no accounts are created or changed."
            )
        if args.prepare_environment:
            prepare_environment(session, settings, administrators[0].id)
        with install_bundle(
            session,
            root=ROOT / "examples/migrations/od600",
            component_root=settings.component_library_root,
            actor_id=administrators[0].id,
            replace_existing=args.replace_existing,
            dry_run=args.check,
        ) as report:
            if args.check:
                session.rollback()
            else:
                session.commit()
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

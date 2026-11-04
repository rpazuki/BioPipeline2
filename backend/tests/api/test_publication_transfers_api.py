"""Exercise publication transport policy, directory assembly, staging and computation."""

import io
import subprocess
import uuid
import zipfile
from contextlib import chdir

import pytest
from sqlalchemy import text

from app.api.main import create_app
from app.application.uploads import stage_inputs, staged_inputs_for_run
from app.domain.task_contract import ResourceLimits
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.execution.docker import DockerAdapter
from app.runner.main import run
from app.settings import load_settings
from app.workers.executor import build_spec

pytestmark = pytest.mark.db

DOC = """pipeline: __NAME__
defaults: {data: $WILL_PROVIDE$}
inputs:
  data: {accept: directory, sources: [shared]}
stages:
  - name: copy
    steps:
      - name: result
        package: shutil
        method: copytree
        parameters: {src: "{data}", dst: outputs/copy, dirs_exist_ok: true}
    outputs:
      results: {path: outputs/copy}
"""


@pytest.fixture
def app(engine, tmp_path):
    settings = load_settings(
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        component_library_root=tmp_path / "components",
        secure_cookies=False,
        upload_directory_max_bytes=128 * 1024,
        upload_directory_max_files=50,
    )
    return create_app(settings=settings, engine=engine)


def upload(client, body=b"content", name="input.txt"):
    opened = client.post(
        "/api/v1/uploads", json={"filename": name, "declared_size_bytes": len(body)}
    )
    assert opened.status_code == 201, opened.text
    upload_id = opened.json()["id"]
    if body:
        appended = client.patch(
            f"/api/v1/uploads/{upload_id}",
            content=body,
            headers={"Content-Range": f"bytes 0-{len(body) - 1}/{len(body)}"},
        )
        assert appended.status_code == 200, appended.text
    completed = client.post(f"/api/v1/uploads/{upload_id}/complete")
    assert completed.status_code == 200, completed.text
    return completed.json()


def directory(client, files=None, zip_upload_id=None, request_id=None):
    return client.post(
        "/api/v1/uploads/directories",
        json={
            "request_id": request_id or str(uuid.uuid4()),
            "name": "data",
            "files": files or [],
            "zip_upload_id": zip_upload_id,
        },
    )


def publication(as_admin, sources, doc=DOC, target="default_value", field_extra=None):
    revision = as_admin.post(
        "/api/v1/pipelines/revisions",
        json={"source_text": doc.replace("__NAME__", f"transfer_{uuid.uuid4().hex[:8]}")},
    )
    assert revision.status_code == 201, revision.text
    slug = f"transfer-{uuid.uuid4().hex[:8]}"
    binding = (
        {"target": target, "binding_key": "data"}
        if target == "default_value"
        else {"target": "step_parameter", "stage": "copy", "step": "result", "binding_key": "src"}
    )
    created = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": slug,
            "pipeline_revision_id": revision.json()["revision_id"],
            "title": "Transfer demo",
            "fields": [
                {
                    "key": "data",
                    "label": "Input directory",
                    "field_type": "directory",
                    "binding": binding,
                    "source_policy": {"sources": sources},
                    **(field_extra or {}),
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert (
        as_admin.post(
            f"/api/v1/publications/{body['publication_id']}/publish",
            params={"revision_id": body["revision_id"]},
        ).status_code
        == 200
    )
    return slug


@pytest.mark.parametrize(
    "container", [False, pytest.param(True, marks=pytest.mark.slow)], ids=["python", "container"]
)
def test_folder_upload_stages_and_executes_without_pipeline_upload_declaration(
    as_admin, as_researcher, app, sessions, tmp_path, container
):
    first = upload(as_researcher)
    zero = upload(as_researcher, b"", "empty.txt")
    files = [
        {"path": "nested/input.txt", "upload_id": first["id"]},
        {"path": "empty.txt", "upload_id": zero["id"]},
    ]
    request_id = str(uuid.uuid4())
    assembled = directory(as_researcher, files, request_id=request_id)
    assert assembled.status_code == 201, assembled.text
    assert (
        directory(as_researcher, files, request_id=request_id).json()["id"]
        == assembled.json()["id"]
    )
    slug = publication(as_admin, ["folder"])
    submitted = as_researcher.post(
        f"/api/v1/catalog/{slug}/runs", json={"values": {"data": assembled.json()["reference"]}}
    )
    assert submitted.status_code == 201, submitted.text
    workspace = tmp_path / "execution"
    workspace.mkdir()
    with sessions() as session:
        staged = staged_inputs_for_run(session, uuid.UUID(submitted.json()["run_id"]))
        stage_inputs(
            staged,
            session=session,
            root=workspace,
            store=PosixArtifactStore(app.state.settings.artifact_root),
        )
        task = session.execute(
            text("SELECT task_spec FROM run_tasks WHERE run_id = :id"),
            {"id": submitted.json()["run_id"]},
        ).scalar_one()
    with chdir(workspace):
        contract = build_spec(
            task_id=uuid.uuid4(),
            run_id=uuid.UUID(submitted.json()["run_id"]),
            attempt=1,
            stage_key="copy",
            task_key="copy",
            task_spec=task,
            limits=ResourceLimits(cpu_millicores=1000, memory_bytes=1024**3, wall_time_seconds=60),
        )
        if container:
            adapter = DockerAdapter(image="biopipeline2/task-base:dev")
            if (
                not adapter.available()
                or not subprocess.run(
                    ["docker", "images", "-q", adapter.image],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                ).stdout.strip()
            ):
                pytest.skip("The task image and Docker are required.")
            executed = adapter.run(contract, workspace, log_path=workspace / "container.log")
            assert executed.exit_code == 0, (workspace / "container.log").read_text()
            outcome = executed.result
        else:
            outcome = run(contract.model_dump(mode="json"), workspace)
    assert outcome["status"] == "succeeded", outcome
    assert (workspace / "outputs/copy/nested/input.txt").read_bytes() == b"content"
    assert (workspace / "outputs/copy/empty.txt").read_bytes() == b""


def test_zip_directory_and_source_restrictions(as_admin, as_researcher, app):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a/input.txt", b"content")
        archive.writestr("empty/", b"")
    original = upload(as_researcher, buffer.getvalue(), "input.zip")
    expanded = directory(as_researcher, zip_upload_id=original["id"])
    assert expanded.status_code == 201, expanded.text
    slug = publication(as_admin, ["zip"])
    good = as_researcher.post(
        f"/api/v1/catalog/{slug}/runs", json={"values": {"data": expanded.json()["reference"]}}
    )
    assert good.status_code == 201, good.text
    ordinary = as_researcher.post(
        f"/api/v1/catalog/{slug}/runs", json={"values": {"data": original["reference"]}}
    )
    assert ordinary.status_code == 422
    folder = directory(as_researcher)
    denied = as_researcher.post(
        f"/api/v1/catalog/{slug}/runs", json={"values": {"data": folder.json()["reference"]}}
    )
    assert denied.status_code == 422 and "folder" in denied.text


def test_uploads_cannot_be_borrowed_from_another_user(as_admin, as_researcher):
    owned = upload(as_admin)
    response = directory(as_researcher, [{"path": "input.txt", "upload_id": owned["id"]}])
    assert response.status_code == 422
    slug = publication(as_admin, ["folder"])
    folder = directory(as_admin)
    submitted = as_researcher.post(
        f"/api/v1/catalog/{slug}/runs", json={"values": {"data": folder.json()["reference"]}}
    )
    assert submitted.status_code == 422


@pytest.mark.parametrize("attribute", ["fixed_value", "default_value"])
def test_published_administrator_inputs_are_available_to_researchers(
    as_admin, as_researcher, attribute
):
    folder = directory(as_admin).json()
    extra = {attribute: folder["reference"]}
    if attribute == "fixed_value":
        extra["visibility"] = "hidden"
    slug = publication(as_admin, ["folder"], field_extra=extra)
    submitted = as_researcher.post(f"/api/v1/catalog/{slug}/runs", json={"values": {}})
    assert submitted.status_code == 201, submitted.text


def test_unsafe_zip_and_assembly_paths_leave_no_directory_artifact(as_researcher, sessions):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape", b"bad")
    original = upload(as_researcher, buffer.getvalue(), "bad.zip")
    assert directory(as_researcher, zip_upload_id=original["id"]).status_code == 422
    assert (
        directory(as_researcher, [{"path": "/bad", "upload_id": original["id"]}]).status_code == 422
    )


def test_stage_parameter_upload_is_resolved_and_staged(as_admin, as_researcher, sessions):
    doc = DOC.replace(
        "defaults: {data: $WILL_PROVIDE$}\ninputs:\n"
        "  data: {accept: directory, sources: [shared]}\n",
        "defaults: {data: placeholder}\n",
    )
    slug = publication(as_admin, ["folder"], doc=doc, target="step_parameter")
    folder = directory(as_researcher)
    response = as_researcher.post(
        f"/api/v1/catalog/{slug}/runs", json={"values": {"data": folder.json()["reference"]}}
    )
    assert response.status_code == 201, response.text
    with sessions() as session:
        assert len(staged_inputs_for_run(session, uuid.UUID(response.json()["run_id"]))) == 1


def test_uploaded_folder_fanout_is_enumerated_in_the_artifact_store(as_admin, as_researcher):
    doc = DOC.replace(
        "    steps:\n", "    fanout:\n      type: folders\n      data_dir: '{data}'\n    steps:\n"
    )
    member = upload(as_researcher)
    folder = directory(
        as_researcher,
        [
            {"path": "one/input.txt", "upload_id": member["id"]},
            {"path": "two/input.txt", "upload_id": member["id"]},
        ],
    )
    slug = publication(as_admin, ["folder"], doc=doc)
    response = as_researcher.post(
        f"/api/v1/catalog/{slug}/runs", json={"values": {"data": folder.json()["reference"]}}
    )
    assert response.status_code == 201, response.text
    assert response.json()["task_count"] == 2


def test_shared_paths_and_http_urls_cannot_bypass_upload_only_policy(as_admin, as_researcher):
    slug = publication(as_admin, ["folder"])
    for value in ["/etc", "https://example.org/input.zip", "../outside"]:
        assert (
            as_researcher.post(
                f"/api/v1/catalog/{slug}/runs", json={"values": {"data": value}}
            ).status_code
            == 422
        )

"""Schedules over HTTP: the same submission, on a clock.

A schedule is composed the way a person composes a run — pick a catalog entry,
fill in its form — and then says when. Everything here is about that being
true, and about a schedule that could never work being refused while somebody
is still looking at it.
"""

from __future__ import annotations

import pathlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

ROOT = pathlib.Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "examples/pipelines/od600_growth_rates.yaml"


def fields(folder_label: str = "Experiment folder") -> list[dict]:
    """Every public input the pipeline asks for, plus one knob."""
    return [
        {
            "key": "experiment_folder",
            "label": folder_label,
            "field_type": "directory",
            "required": True,
            "binding": {"target": "default_value", "binding_key": "data_root"},
        },
        {
            "key": "mapping",
            "label": "Mapping file",
            "field_type": "file",
            "required": True,
            "binding": {"target": "default_value", "binding_key": "mapping_yaml"},
        },
        {
            "key": "window",
            "label": "Smoothing window",
            "field_type": "integer",
            "required": False,
            "default_value": 5,
            "binding": {
                "target": "step_parameter",
                "stage": "fit",
                "step": "df_fit_max_growth_rate",
                "binding_key": "moving_window_size",
            },
        },
    ]


@dataclass(frozen=True)
class Entry:
    slug: str
    publication_id: str
    pipeline_revision_id: str


def publish_revision(
    as_admin: TestClient,
    slug: str,
    pipeline_revision_id: str,
    title: str,
    folder_label: str = "Experiment folder",
) -> str:
    created = as_admin.post(
        "/api/v1/publications/revisions",
        json={
            "slug": slug,
            "pipeline_revision_id": pipeline_revision_id,
            "title": title,
            "fields": fields(folder_label),
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    opened = as_admin.post(
        f"/api/v1/publications/{body['publication_id']}/publish",
        params={"revision_id": body["revision_id"]},
    )
    assert opened.status_code == 200, opened.text
    return body["publication_id"]


@pytest.fixture
def entry(as_admin: TestClient) -> Entry:
    source = EXAMPLE.read_text().replace(
        "pipeline: od600_growth_rates", f"pipeline: sch_{uuid.uuid4().hex[:8]}"
    )
    revision = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": source})
    assert revision.status_code == 201, revision.text
    pipeline_revision_id = revision.json()["revision_id"]
    slug = f"nightly-{uuid.uuid4().hex[:8]}"
    publication_id = publish_revision(as_admin, slug, pipeline_revision_id, "OD600 growth rates")
    return Entry(slug, publication_id, pipeline_revision_id)


def payload(slug: str, **overrides) -> dict:
    body = {
        "slug": slug,
        "title": "Nightly growth rates",
        "values": {"experiment_folder": "/mnt/lab/run7", "mapping": "/mnt/lab/map.yaml"},
        "rrule": "FREQ=DAILY;BYHOUR=2;BYMINUTE=0",
        "timezone": "Europe/London",
    }
    body.update(overrides)
    return body


def create(client: TestClient, entry, **overrides):
    slug = entry.slug if isinstance(entry, Entry) else entry
    return client.post("/api/v1/schedules", json=payload(slug, **overrides))


# --- composing one ---------------------------------------------------------


def test_a_researcher_can_schedule_a_catalog_entry(as_researcher, entry):
    response = create(as_researcher, entry)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "active"
    assert body["slug"] == entry.slug
    assert body["next_fire_at"] is not None
    assert body["values"]["experiment_folder"] == "/mnt/lab/run7"


def test_the_rule_is_stored_with_its_own_start(as_researcher, entry):
    """So a daylight-saving shift cannot move a nightly job for ever."""
    body = create(as_researcher, entry).json()
    assert body["rrule"].startswith("DTSTART:")
    assert "FREQ=DAILY" in body["rrule"]


def test_an_interval_schedule_is_accepted_too(as_researcher, entry):
    """The current system's representation, kept so nothing has to convert."""
    response = create(as_researcher, entry, rrule=None, interval_seconds=3600)
    assert response.status_code == 201, response.text
    assert response.json()["interval_seconds"] == 3600


def test_a_schedule_must_pick_exactly_one_recurrence(as_researcher, entry):
    """The same rule the database enforces, refused where a form can show it.

    400 rather than 422: the request itself is malformed, which is what this
    API says 400 for.
    """
    both = create(as_researcher, entry, interval_seconds=3600)
    neither = create(as_researcher, entry, rrule=None)
    assert both.status_code == 400
    assert neither.status_code == 400
    assert "exactly one" in both.text


def test_values_that_could_never_run_are_refused_now_not_at_3am(as_researcher, entry):
    response = create(as_researcher, entry, values={"window": 5})
    assert response.status_code == 422, response.text
    assert "Experiment folder" in response.text


def test_a_recurrence_with_no_window_at_all_is_refused(as_researcher, entry):
    response = create(
        as_researcher,
        entry,
        rrule="FREQ=DAILY;COUNT=1",
        end_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
    )
    assert response.status_code == 422, response.text
    assert "never run" in response.text


def test_an_unknown_entry_is_a_404(as_researcher):
    response = create(as_researcher, "no-such-entry")
    assert response.status_code == 404


def test_scheduling_needs_a_signed_in_user(api, entry):
    assert create(api, entry).status_code == 401


def test_the_defaults_cannot_pile_runs_up(as_researcher, entry):
    """Nobody is watching a schedule, so `skip` with one concurrent run is
    what stops a slow pipeline queueing a day of itself."""
    body = create(as_researcher, entry).json()
    assert body["overlap_policy"] == "skip"
    assert body["max_concurrent_runs"] == 1
    assert body["catchup_policy"] == "skip_missed"


# --- seeing them -----------------------------------------------------------


def test_a_schedule_is_listed_with_the_entry_it_runs(as_researcher, entry):
    create(as_researcher, entry)
    listed = as_researcher.get("/api/v1/schedules")
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["slug"] == entry.slug
    assert item["entry_title"] == "OD600 growth rates"
    assert item["revision_is_current"] is True


def test_a_schedule_says_when_its_entry_has_moved_on(as_admin, as_researcher, entry):
    """It pins its revision deliberately. Not saying so would let it fall
    quietly behind a re-published entry with nobody able to tell."""
    created = create(as_researcher, entry).json()
    publish_revision(as_admin, entry.slug, entry.pipeline_revision_id, "OD600 growth rates v2")
    detail = as_researcher.get(f"/api/v1/schedules/{created['id']}").json()
    assert detail["revision_is_current"] is False
    assert detail["version"] == 1  # still running what it was created against


def test_the_detail_carries_the_fields_so_values_read_as_words(as_researcher, entry):
    created = create(as_researcher, entry).json()
    detail = as_researcher.get(f"/api/v1/schedules/{created['id']}").json()
    labels = {field["key"]: field["label"] for field in detail["fields"]}
    assert labels["experiment_folder"] == "Experiment folder"


def test_the_labels_are_the_ones_the_values_were_collected_with(as_admin, as_researcher, entry):
    """From the revision the schedule pins, not from whatever the entry says
    now. Relabelling a field would otherwise put words on a stored value that
    were never used to ask for it."""
    created = create(as_researcher, entry).json()
    publish_revision(
        as_admin,
        entry.slug,
        entry.pipeline_revision_id,
        "OD600 growth rates",
        folder_label="Plate reader export folder",
    )
    detail = as_researcher.get(f"/api/v1/schedules/{created['id']}").json()
    labels = {field["key"]: field["label"] for field in detail["fields"]}
    assert labels["experiment_folder"] == "Experiment folder"


def test_a_schedule_records_that_it_was_created(as_researcher, entry):
    created = create(as_researcher, entry).json()
    detail = as_researcher.get(f"/api/v1/schedules/{created['id']}").json()
    assert [event["event_type"] for event in detail["events"]] == ["created"]


# --- whose it is -----------------------------------------------------------


def test_somebody_else_s_schedule_is_a_404(as_researcher, client_for, sessions, entry):
    created = create(as_researcher, entry).json()
    from tests.api.conftest import PASSWORD, _make_user

    _, email = _make_user(sessions, "researcher")
    other = client_for()
    other.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert other.get(f"/api/v1/schedules/{created['id']}").status_code == 404
    assert other.get("/api/v1/schedules").json()["items"] == []


def test_an_admin_sees_every_schedule(as_admin, as_researcher, entry):
    create(as_researcher, entry)
    listed = as_admin.get("/api/v1/schedules").json()
    assert len(listed["items"]) == 1


def test_somebody_else_cannot_pause_it(as_researcher, client_for, sessions, entry):
    created = create(as_researcher, entry).json()
    from tests.api.conftest import PASSWORD, _make_user

    _, email = _make_user(sessions, "researcher")
    other = client_for()
    other.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert other.post(f"/api/v1/schedules/{created['id']}/pause").status_code == 404


# --- administering ---------------------------------------------------------


def test_pausing_stops_it_being_due(as_researcher, entry):
    created = create(as_researcher, entry).json()
    paused = as_researcher.post(f"/api/v1/schedules/{created['id']}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"


def test_resuming_starts_from_the_next_window(as_researcher, entry):
    """A fortnight paused must not answer with a fortnight of runs."""
    created = create(as_researcher, entry, rrule=None, interval_seconds=3600).json()
    as_researcher.post(f"/api/v1/schedules/{created['id']}/pause")
    resumed = as_researcher.post(f"/api/v1/schedules/{created['id']}/resume").json()
    assert resumed["status"] == "active"
    assert datetime.fromisoformat(resumed["next_fire_at"]) > datetime.now(UTC)


def test_archiving_retires_it(as_researcher, entry):
    created = create(as_researcher, entry).json()
    archived = as_researcher.post(f"/api/v1/schedules/{created['id']}/archive").json()
    assert archived["status"] == "archived"
    assert archived["next_fire_at"] is None
    # Gone from the list of things that will happen, not from the record.
    assert as_researcher.get("/api/v1/schedules").json()["items"] == []
    assert as_researcher.get(f"/api/v1/schedules/{created['id']}").status_code == 200


def test_every_change_is_recorded(as_researcher, entry):
    created = create(as_researcher, entry).json()
    as_researcher.post(f"/api/v1/schedules/{created['id']}/pause")
    as_researcher.post(f"/api/v1/schedules/{created['id']}/resume")
    detail = as_researcher.get(f"/api/v1/schedules/{created['id']}").json()
    assert [event["event_type"] for event in detail["events"]] == ["resumed", "paused", "created"]


# --- what a researcher sees of a scheduled run -----------------------------


def test_a_run_says_what_started_it(as_researcher, entry):
    """Now that a clock can start one, "I did not submit this" is a question
    somebody will ask of their own run list."""
    listed = as_researcher.get("/api/v1/runs")
    assert listed.status_code == 200
    assert all("requested_from" in item for item in listed.json()["items"])

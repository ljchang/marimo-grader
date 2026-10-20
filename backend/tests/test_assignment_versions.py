"""The assignment detail page's version history."""

from __future__ import annotations

from tests.conftest import login
from tests.test_publish_public import Q2, _publish


def test_version_history_is_for_instructors(client, seed):
    csrf = login(client, "prof")
    _publish(client, csrf, seed, questions=Q2)
    rows = client.get(
        f"/api/v1/offerings/{seed.offering_id}/assignments/{seed.assignment_id}/versions"
    ).json()
    assert [r["version"] for r in rows] == sorted((r["version"] for r in rows), reverse=True)
    assert rows[0]["published_by"] == "prof" and rows[0]["student_url"].endswith("/student.py")
    assert rows[0]["created_at"].endswith("+00:00")  # UTC said, not left for the browser to guess
    client.cookies.clear()
    login(client, "ta1")
    r = client.get(
        f"/api/v1/offerings/{seed.offering_id}/assignments/{seed.assignment_id}/versions"
    )
    assert r.status_code == 403

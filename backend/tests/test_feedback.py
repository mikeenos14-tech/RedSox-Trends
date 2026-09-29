"""'Something look off?' reports: stored durably, validated, rate limited,
and readable only with the admin token."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import feedback, main


@pytest.fixture
def client(season_2026, temp_ai_store, monkeypatch):
    feedback._recent_by_client.clear()
    monkeypatch.delenv("FEEDBACK_ADMIN_TOKEN", raising=False)
    return TestClient(main.app)


REPORT = {
    "section": "recap",
    "page": "/",
    "note": "It says a two-run double but only one run scored.",
    "shown_text": "Bregman added a two-run double in the ninth.",
}


def test_report_is_stored_in_the_database(client, temp_ai_store):
    resp = client.post("/api/feedback", json=REPORT)
    assert resp.status_code == 201
    # Verified at the database level, not just the API's own success reply.
    row = sqlite3.connect(temp_ai_store).execute("SELECT section, page, note, shown_text FROM feedback").fetchone()
    assert row == (REPORT["section"], REPORT["page"], REPORT["note"], REPORT["shown_text"])


def test_rejects_unknown_sections_and_oversized_input(client):
    assert client.post("/api/feedback", json={**REPORT, "section": "not-a-section"}).status_code == 400
    assert client.post("/api/feedback", json={**REPORT, "note": "x" * 1001}).status_code == 422


def test_rate_limit(client):
    codes = [client.post("/api/feedback", json=REPORT, headers={"X-Forwarded-For": "1.2.3.4"}).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]
    # A different reader isn't affected.
    assert client.post("/api/feedback", json=REPORT, headers={"X-Forwarded-For": "5.6.7.8"}).status_code == 201


def test_admin_endpoint_is_off_without_a_token(client):
    assert client.get("/api/admin/feedback").status_code == 404


def test_admin_requires_the_right_token(client, monkeypatch):
    monkeypatch.setenv("FEEDBACK_ADMIN_TOKEN", "correct-horse")
    client.post("/api/feedback", json=REPORT)
    assert client.get("/api/admin/feedback").status_code == 401
    assert client.get("/api/admin/feedback", headers={"Authorization": "Bearer wrong"}).status_code == 401
    resp = client.get("/api/admin/feedback", headers={"Authorization": "Bearer correct-horse"})
    assert resp.status_code == 200
    [report] = resp.json()["reports"]
    assert report["note"] == REPORT["note"] and report["shown_text"] == REPORT["shown_text"]

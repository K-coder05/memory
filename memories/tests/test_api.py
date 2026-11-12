from datetime import datetime, timezone as dt_timezone

import pytest
from rest_framework.test import APIClient

from memories.models import Memory

pytestmark = pytest.mark.django_db  # every test in this file may use the DB


def utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


def test_requires_authentication():
    resp = APIClient().get("/memories")
    assert resp.status_code == 401


def test_create_memory_assigns_requesting_user(alice, alice_gmail, client_for):
    resp = client_for(alice).post(
        "/memories",
        {
            "source_id": alice_gmail.id,
            "content": "Dinner with Sam on Friday",
            "occurred_at": "2024-03-01T19:00:00Z",
            "metadata": {"from": "sam@example.com"},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    memory = Memory.objects.get(id=resp.data["id"])
    assert memory.user == alice
    assert resp.data["source"]["kind"] == "gmail"
    assert resp.data["metadata"] == {"from": "sam@example.com"}


def test_user_cannot_read_another_users_memory(alice, bob, bob_slack, make_memory, client_for):
    secret = make_memory(bob, bob_slack, content="bob's secret")
    resp = client_for(alice).get(f"/memories/{secret.id}")
    assert resp.status_code == 404  # not 403: don't even confirm it exists


def test_list_only_returns_own_memories(alice, bob, alice_gmail, bob_slack, make_memory, client_for):
    mine = make_memory(alice, alice_gmail, content="mine")
    make_memory(bob, bob_slack, content="not mine")
    resp = client_for(alice).get("/memories")
    assert resp.status_code == 200
    assert [m["id"] for m in resp.data["results"]] == [mine.id]


def test_cannot_attach_memory_to_another_users_source(alice, bob_slack, client_for):
    resp = client_for(alice).post(
        "/memories",
        {"source_id": bob_slack.id, "content": "sneaky", "occurred_at": "2024-03-01T00:00:00Z"},
        format="json",
    )
    assert resp.status_code == 400
    assert "source_id" in resp.data
    assert Memory.objects.count() == 0


def test_filter_by_source_kind(alice, alice_gmail, alice_slack, make_memory, client_for):
    email = make_memory(alice, alice_gmail, content="an email")
    make_memory(alice, alice_slack, content="a slack message")
    resp = client_for(alice).get("/memories", {"source": "gmail"})
    assert [m["id"] for m in resp.data["results"]] == [email.id]


def test_filter_since(alice, alice_gmail, make_memory, client_for):
    make_memory(alice, alice_gmail, content="old", when=utc(2023, 6, 1))
    new = make_memory(alice, alice_gmail, content="new", when=utc(2024, 6, 1))
    resp = client_for(alice).get("/memories", {"since": "2024-01-01"})
    assert [m["id"] for m in resp.data["results"]] == [new.id]


def test_since_rejects_garbage(alice, client_for):
    resp = client_for(alice).get("/memories", {"since": "last tuesday"})
    assert resp.status_code == 400


def test_search_is_case_insensitive(alice, alice_gmail, make_memory, client_for):
    hit = make_memory(alice, alice_gmail, content="Flight to TOKYO confirmed")
    make_memory(alice, alice_gmail, content="Grocery list")
    resp = client_for(alice).get("/memories", {"q": "tokyo"})
    assert [m["id"] for m in resp.data["results"]] == [hit.id]


def test_list_is_paginated_newest_first(alice, alice_gmail, make_memory, client_for):
    for day in range(1, 26):  # 25 memories, Jan 1..25
        make_memory(alice, alice_gmail, content=f"day {day}", when=utc(2024, 1, day))
    resp = client_for(alice).get("/memories")
    assert resp.data["count"] == 25
    assert len(resp.data["results"]) == 20
    assert resp.data["next"] is not None
    assert resp.data["results"][0]["content"] == "day 25"
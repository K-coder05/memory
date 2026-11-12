from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from memories.models import Memory, Source


@pytest.fixture
def make_user(db):  # requesting `db` gives this fixture database access
    def _make(username):
        return get_user_model().objects.create_user(username=username, password="pw")
    return _make


@pytest.fixture
def alice(make_user):
    return make_user("alice")


@pytest.fixture
def bob(make_user):
    return make_user("bob")


@pytest.fixture
def alice_gmail(alice):
    return Source.objects.create(user=alice, kind="gmail", name="alice@example.com")


@pytest.fixture
def alice_slack(alice):
    return Source.objects.create(user=alice, kind="slack", name="acme")


@pytest.fixture
def bob_slack(bob):
    return Source.objects.create(user=bob, kind="slack", name="bobco")


@pytest.fixture
def client_for():
    """client_for(user) -> an APIClient already logged in as that user."""
    def _client(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client
    return _client


@pytest.fixture
def make_memory():
    def _make(user, source, content="hello", when=None, **extra):
        return Memory.objects.create(
            user=user,
            source=source,
            content=content,
            occurred_at=when or datetime(2024, 1, 15, tzinfo=dt_timezone.utc),
            **extra,
        )
    return _make
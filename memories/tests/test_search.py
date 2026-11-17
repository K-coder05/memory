import pytest

from memories.models import EMBEDDING_DIM
from memories.search import hybrid_search, keyword_search, vector_search

pytestmark = pytest.mark.django_db


def unit(i, dim=EMBEDDING_DIM):
    """A vector pointing along axis i: cosine distance 0 to itself, 1 to other axes."""
    v = [0.0] * dim
    v[i] = 1.0
    return v


def test_vector_search_is_scoped_to_user(alice, bob, alice_gmail, bob_slack, make_memory):
    mine = make_memory(alice, alice_gmail, content="x", embedding=unit(0))
    make_memory(bob, bob_slack, content="x", embedding=unit(0))
    assert vector_search(alice.id, unit(0), k=5) == [mine.id]


def test_keyword_search_is_scoped_to_user(alice, bob, alice_gmail, bob_slack, make_memory):
    mine = make_memory(alice, alice_gmail, content="budget meeting")
    make_memory(bob, bob_slack, content="budget meeting")
    assert keyword_search(alice.id, "budget", k=5) == [mine.id]


def test_hybrid_search_is_scoped_to_user(alice, bob, alice_gmail, bob_slack, make_memory):
    mine = make_memory(alice, alice_gmail, content="budget meeting", embedding=unit(0))
    make_memory(bob, bob_slack, content="budget meeting", embedding=unit(0))
    assert hybrid_search(alice.id, "budget", unit(0), k=5) == [mine.id]


def test_vector_search_orders_by_cosine_distance(alice, alice_gmail, make_memory):
    near = make_memory(alice, alice_gmail, content="near", embedding=unit(0))
    far = make_memory(alice, alice_gmail, content="far", embedding=unit(1))
    assert vector_search(alice.id, unit(0), k=2) == [near.id, far.id]


def test_keyword_search_matches_any_word(alice, alice_gmail, make_memory):
    # "or" semantics: a natural-language question shouldn't need every word to match
    hit = make_memory(alice, alice_gmail, content="the budget was approved")
    make_memory(alice, alice_gmail, content="lunch plans")
    assert keyword_search(alice.id, "what happened with the budget and the roadmap", k=5) == [hit.id]


def test_hybrid_ranks_documents_found_by_both_methods_first(alice, alice_gmail, make_memory):
    both = make_memory(alice, alice_gmail, content="budget review", embedding=unit(0))
    keyword_only = make_memory(alice, alice_gmail, content="quarterly budget", embedding=unit(1))
    vector_only = make_memory(alice, alice_gmail, content="lunch plans", embedding=unit(0))
    ids = hybrid_search(alice.id, "budget", unit(0), k=3)
    assert ids[0] == both.id
    assert set(ids) == {both.id, keyword_only.id, vector_only.id}


def test_force_index_does_not_change_results(alice, alice_gmail, make_memory):
    near = make_memory(alice, alice_gmail, content="near", embedding=unit(0))
    far = make_memory(alice, alice_gmail, content="far", embedding=unit(1))
    assert vector_search(alice.id, unit(0), k=2, force_index=True) == [near.id, far.id]

"""Verify exact complete-input and aggregate embedding budgets."""

import pytest

from app.ingestion.tokens import InputBudget, count_tokens, validate_request


def test_complete_input_counts_context():
    """Context consumes the same token and character allowance as source body."""
    body = " hello" * 8190
    assert InputBudget(max_chars=100_000).accepts(body)
    assert not InputBudget(max_chars=100_000).accepts("context heading\n\n" + body)


def test_exact_token_boundary():
    """The maximum is inclusive and oversized source is never truncated."""
    text = " hello" * 8192
    assert count_tokens(text) == 8192
    assert validate_request([text], model="text-embedding-3-large") == (8192,)
    with pytest.raises(ValueError, match="input 0 exceeds"):
        validate_request([text + " hello"], model="text-embedding-3-large")


def test_aggregate_boundary():
    """Individually valid inputs cannot exceed the request total."""
    inputs = [" hello" * 8000] * 37 + [" hello" * 4000]
    assert sum(validate_request(inputs, model="text-embedding-3-large")) == 300_000
    with pytest.raises(ValueError, match="aggregate"):
        validate_request([*inputs, " hello"], model="text-embedding-3-large")


def test_character_and_literal_special_token_budgets():
    """Character limits apply independently and special-looking source remains literal."""
    assert not InputBudget(max_chars=3).accepts("hello")
    assert count_tokens("<|endoftext|>") > 1


def test_input_array_limit():
    """Reject oversized arrays before any model call."""
    with pytest.raises(ValueError, match="2048 inputs"):
        validate_request(["hello"] * 2049, model="text-embedding-3-large")

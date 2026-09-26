"""Tests for parsing the Planner's step-review response into a validated StepReview."""

import pytest

from multiagent.agents.planner.review_parser import (
    StepReviewParsingError,
    parse_step_review_response,
)
from multiagent.contracts.messages import StepReview


def test_parses_a_clean_approved_review():
    raw = '{"kind": "step_review", "step_id": 1, "approved": true, "feedback": "looks correct"}'

    review = parse_step_review_response(raw)

    assert isinstance(review, StepReview)
    assert review.approved is True


def test_parses_a_clean_rejected_review():
    raw = '{"kind": "step_review", "step_id": 1, "approved": false, "feedback": "test does not cover the change"}'

    review = parse_step_review_response(raw)

    assert review.approved is False
    assert "does not cover" in review.feedback


def test_strips_a_think_block_first():
    raw = "<think>let me check this change</think>" + (
        '{"kind": "step_review", "step_id": 1, "approved": true, "feedback": "ok"}'
    )

    review = parse_step_review_response(raw)

    assert review.approved is True


def test_raises_on_malformed_json():
    with pytest.raises(StepReviewParsingError):
        parse_step_review_response('{"kind": "step_review", "approved": ')


def test_raises_when_schema_does_not_match():
    with pytest.raises(StepReviewParsingError):
        parse_step_review_response('{"kind": "step_review", "step_id": 1}')  # missing approved/feedback


def test_raises_when_no_json_present_at_all():
    with pytest.raises(StepReviewParsingError):
        parse_step_review_response("<think>hmm</think>I can't tell.")

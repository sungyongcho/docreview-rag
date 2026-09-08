"""File-based dataset persistence, read-only built-ins, and optimistic edits."""

import asyncio
import json

import pytest

from app.api.admin_schemas import EvaluationRunRequest
from app.evals.admin import EvaluationAdminService
from app.evals.golden_admin import GoldenAdminService
from app.evals.source_binding import BoundGolden


def absent_case(question="Question?"):
    """Construct a valid authored negative evaluation case."""
    return dict(
        id="test-01",
        question=question,
        category="absent",
        facet="policy",
        tags=[],
        answers=[],
        expected_label="NOT_IN_DOCS",
        reference_answer="NOT_IN_DOCS",
        note="Negative case.",
        curation_status="user-authored",
        approval_status="pending-author-approval",
        human_verified=False,
    )


@pytest.fixture
def service(tmp_path):
    """Provide a bundled file and isolate every user file from the real corpus."""
    (tmp_path / "retrieval.json").write_text(json.dumps([absent_case()]))
    return GoldenAdminService(golden_dir=tmp_path, corpus_dir=tmp_path)


def test_files_survive_service_recreation_and_feed_evaluation(service, tmp_path):
    """A saved dataset is usable without DB revision rows and cannot mutate its built-in parent."""

    async def exercise():
        original = (tmp_path / "retrieval.json").read_bytes()
        draft = await service.create_draft("sec-en", filename="my-eval.json")
        edited = await service.replace_case(
            draft.revision_id,
            "test-01",
            expected_sha256=draft.sha256,
            payload=absent_case("Changed?"),
        )
        reloaded = GoldenAdminService(golden_dir=tmp_path).get(draft.revision_id)
        assert reloaded.payload[0]["question"] == "Changed?"
        assert reloaded.sha256 == edited.sha256
        assert reloaded.file_content["registry"] == "sec"
        assert (tmp_path / "retrieval.json").read_bytes() == original
        evaluation = EvaluationAdminService()
        evaluation._golden_dir = tmp_path
        payload, digest = await evaluation._golden_revision_payload(
            EvaluationRunRequest(suite_id="sec-en", golden_revision_id=draft.revision_id)
        )
        assert payload[0]["question"] == "Changed?" and digest == edited.sha256
        with pytest.raises(ValueError, match="changed"):
            await service.replace_case(
                draft.revision_id,
                "test-01",
                expected_sha256=draft.sha256,
                payload=absent_case("Lost update?"),
            )

    asyncio.run(exercise())


def test_empty_file_can_receive_a_new_question(service):
    """An empty custom dataset can be authored and cannot pass preparation empty."""

    async def exercise():
        draft = await service.create_draft("sec-en", filename="empty.json", empty=True)
        assert not draft.payload
        with pytest.raises(ValueError, match="at least one"):
            await service.validate(draft.revision_id, expected_sha256=draft.sha256)
        saved = await service.replace_case(
            draft.revision_id, "test-01", expected_sha256=draft.sha256, payload=absent_case()
        )
        assert len(saved.payload) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "filename", ["../escape.json", "retrieval.json", "bad/path.json", "wrong.txt"]
)
def test_invalid_or_builtin_filenames_cannot_be_written(service, filename):
    """Reject traversal, built-in replacement, and non-JSON names."""
    with pytest.raises(ValueError):
        asyncio.run(service.create_draft("sec-en", filename=filename))


def test_checks_are_invalidated_by_editing(service, monkeypatch):
    """Source checks bind to exact content and never grant human verification."""
    monkeypatch.setattr("app.evals.golden_admin.bind_golden", lambda *args: BoundGolden((), ()))

    async def exercise():
        draft = await service.create_draft("sec-en", filename="checked.json")
        checked = await service.validate(draft.revision_id, expected_sha256=draft.sha256)
        assert checked.status == "validated" and checked.payload[0]["human_verified"] is False
        edited = await service.replace_case(
            checked.revision_id,
            "test-01",
            expected_sha256=checked.sha256,
            payload=absent_case("Changed?"),
        )
        assert edited.status == "draft"
        assert edited.file_content["checked_sha256"] is None

    asyncio.run(exercise())


def test_existing_filename_is_not_overwritten(service):
    """Creating the same filename twice leaves the original intact."""

    async def exercise():
        first = await service.create_draft("sec-en", filename="mine.json")
        with pytest.raises(ValueError, match="already exists"):
            await service.create_draft("sec-en", filename="mine.json", empty=True)
        assert service.get(first.revision_id) == first

    asyncio.run(exercise())


def test_invalid_question_error_is_concise_and_does_not_include_input(service):
    """Reject contradictory authoring data without leaking Pydantic input dumps into the UI."""
    from app.evals.loader import GoldenDataError

    payload = {**absent_case(), "question": {"secret": "PRIVATE INPUT"}}
    with pytest.raises(GoldenDataError) as captured:
        asyncio.run(service.replace_case(1, "test-01", expected_sha256="a" * 64, payload=payload))
    message = str(captured.value)
    assert "indicated question fields" in message
    assert "PRIVATE INPUT" not in message
    assert "input_value" not in message
    assert "pydantic.dev" not in message


def test_incomplete_drafts_survive_reload_and_block_the_entire_evaluation(service, tmp_path):
    """Never lose partial authoring or silently skip it when evaluating the dataset."""
    from app.evals.drafts import DraftInputError, executable_cases

    async def exercise():
        created = await service.create_draft("sec-en", filename="unfinished.json", empty=True)
        saved = await service.replace_case(
            created.revision_id,
            "draft-1",
            expected_sha256=created.sha256,
            payload={"id": "draft-1", "question": "", "tags": ["  메모리 위험  ", "메모리 위험"]},
        )
        again = GoldenAdminService(golden_dir=tmp_path).get(saved.revision_id)
        assert again.payload[0]["tags"] == ["메모리 위험"]
        assert again.payload[0]["category"] is None
        assert again.completion["draft-1"]
        with pytest.raises(DraftInputError):
            executable_cases(again.payload)
        evaluation = EvaluationAdminService()
        evaluation._golden_dir = tmp_path
        request = EvaluationRunRequest(suite_id="sec-en", golden_revision_id=again.revision_id)
        assert (await evaluation.preparation(request)).state == "draft_incomplete"
        with pytest.raises(DraftInputError):
            await evaluation._evaluation_cases(request)
        finished = await service.replace_case(
            again.revision_id,
            "draft-1",
            expected_sha256=again.sha256,
            payload={**absent_case(), "id": "draft-1", "tags": ["한글 태그"]},
        )
        assert not finished.completion["draft-1"]
        assert len(executable_cases(finished.payload)) == 1

    asyncio.run(exercise())


def test_multiple_blank_drafts_are_saved_without_duplicate_question_errors(service):
    """Distinct IDs may hold unfinished questions until the dataset is checked."""

    async def exercise():
        item = await service.create_draft("sec-en", filename="blank.json", empty=True)
        for identity in ["draft-1", "draft-2"]:
            item = await service.replace_case(
                item.revision_id, identity, expected_sha256=item.sha256, payload={"id": identity}
            )
        assert len(item.payload) == 2
        assert all(item.completion.values())

    asyncio.run(exercise())

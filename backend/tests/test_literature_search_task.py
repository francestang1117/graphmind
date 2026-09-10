"""Worker tests for the bounded PubMed search task."""

from app.services.medical.literature.exceptions import LiteratureProviderError
from app.services.medical.literature.query_builder import build_literature_query
from app.tasks import literature_search

from test_literature_repository import _document, _page, _setup


def _create_run():
    sessions, repository = _setup()
    with sessions() as db:
        db.add(_document("document-a", "user-a", "workspace-a"))
        db.commit()
    run, _ = repository.create_or_reuse(
        query=build_literature_query("What is known about Fabry disease?"),
        user_id="user-a",
        workspace_id="workspace-a",
        document_id="document-a",
        external_search_confirmed=True,
    )
    return repository, run["run_id"]


def test_worker_claims_fetches_and_saves_a_search(monkeypatch) -> None:
    repository, run_id = _create_run()
    captured = {}

    class FakeProvider:
        async def search(self, query):
            captured["query"] = query
            return _page()

    monkeypatch.setattr(literature_search, "literature_repository", repository)
    monkeypatch.setattr(literature_search, "PubMedProvider", FakeProvider)

    result = literature_search.run_literature_search_once(run_id)

    assert result["status"] == "succeeded"
    assert captured["query"].normalized_query
    assert repository.get_run(run_id, "user-a", "workspace-a")["result_count"] == 1


def test_worker_records_provider_failure_without_leaking_the_query(monkeypatch) -> None:
    repository, run_id = _create_run()

    class FailingProvider:
        async def search(self, _query):
            raise LiteratureProviderError(
                "PubMed is temporarily unavailable.",
                code="literature_provider_unavailable",
                retryable=True,
            )

    monkeypatch.setattr(literature_search, "literature_repository", repository)
    monkeypatch.setattr(literature_search, "PubMedProvider", FailingProvider)

    result = literature_search.run_literature_search_once(run_id)

    assert result["status"] == "failed"
    assert result["error_code"] == "literature_provider_unavailable"
    saved = repository.get_run(run_id, "user-a", "workspace-a")
    assert saved["status"] == "failed"
    assert "Fabry" not in saved["error_message"]

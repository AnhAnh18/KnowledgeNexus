import pytest

from knowledgenexus.foundation.application.use_cases.compose_m10_snapshot import (
    ComposeM10Snapshot,
    M10CompositionFailure,
    M10CompositionFailureCategory,
)
from knowledgenexus.foundation.domain.models.m10_composition import M10ConfluenceHandoff, M10GitHandoff
from knowledgenexus.foundation.domain.models.m10_snapshot import M10SnapshotRequest
from tests.foundation.domain.models.test_m10_composition import _handoffs, _request


class Adapter:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def collect(self, request):
        self.calls += 1
        return self.value


def test_use_case_injected_adapters_are_called_once_and_composition_is_atomic(tmp_path):
    confluence, git = _handoffs()
    confluence_adapter, git_adapter = Adapter(confluence), Adapter(git)
    result = ComposeM10Snapshot(confluence_adapter=confluence_adapter, git_adapter=git_adapter).execute(_request(tmp_path))
    assert result.projection is not None
    assert confluence_adapter.calls == git_adapter.calls == 1


@pytest.mark.parametrize("bad", [None, object(), {"run_id": "x"}])
def test_use_case_rejects_wrong_request_before_dependency_calls(tmp_path, bad):
    confluence, git = _handoffs()
    left, right = Adapter(confluence), Adapter(git)
    with pytest.raises(M10CompositionFailure) as exc:
        ComposeM10Snapshot(confluence_adapter=left, git_adapter=right).execute(bad)
    assert exc.value.category is M10CompositionFailureCategory.INVALID_REQUEST
    assert left.calls == right.calls == 0


def test_use_case_sanitizes_adapter_failure(tmp_path):
    class Exploding:
        def collect(self, request):
            raise RuntimeError("secret path and page content")

    _, git = _handoffs()
    with pytest.raises(M10CompositionFailure) as exc:
        ComposeM10Snapshot(confluence_adapter=Exploding(), git_adapter=Adapter(git)).execute(_request(tmp_path))
    assert exc.value.category is M10CompositionFailureCategory.ADAPTER
    assert "secret" not in str(exc.value)


def test_use_case_rejects_wrong_handoff_as_adapter_failure(tmp_path):
    _, git = _handoffs()
    with pytest.raises(M10CompositionFailure) as exc:
        ComposeM10Snapshot(confluence_adapter=Adapter(object()), git_adapter=Adapter(git)).execute(_request(tmp_path))
    assert exc.value.category is M10CompositionFailureCategory.ADAPTER


def test_constructor_rejects_non_callable_adapters_and_validator():
    with pytest.raises(M10CompositionFailure) as first: ComposeM10Snapshot(confluence_adapter=object(), git_adapter=object())
    assert first.value.category is M10CompositionFailureCategory.ADAPTER
    with pytest.raises(M10CompositionFailure) as second: ComposeM10Snapshot(confluence_adapter=Adapter(None), git_adapter=Adapter(None), schema_validator=object())
    assert second.value.category is M10CompositionFailureCategory.ADAPTER


def test_noop_canonical_validator_cannot_bypass_schema_and_calls_zero_adapters(tmp_path):
    confluence, git = _handoffs()
    left, right = Adapter(confluence), Adapter(git)
    class Noop:
        def validate_record(self, schema_name, record): return None
    with pytest.raises(M10CompositionFailure) as exc:
        ComposeM10Snapshot(confluence_adapter=left, git_adapter=right, schema_validator=Noop(), canonical_schema_validator=Noop())
    assert exc.value.category is M10CompositionFailureCategory.ADAPTER
    assert left.calls == right.calls == 0


def test_canonical_validator_subclass_is_rejected_before_adapter_calls():
    from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
    class DerivedValidator(FoundationSchemaValidator):
        pass
    left, right = Adapter(None), Adapter(None)
    with pytest.raises(M10CompositionFailure) as exc:
        ComposeM10Snapshot(confluence_adapter=left, git_adapter=right, canonical_schema_validator=DerivedValidator())
    assert exc.value.category is M10CompositionFailureCategory.ADAPTER
    assert left.calls == right.calls == 0


def test_validator_mutation_does_not_reach_projection(tmp_path):
    confluence, git = _handoffs()
    class MutatingValidator:
        def validate_record(self, schema_name, record):
            record["mutated"] = True
    with pytest.raises(M10CompositionFailure) as exc:
        ComposeM10Snapshot(confluence_adapter=Adapter(confluence), git_adapter=Adapter(git), schema_validator=MutatingValidator()).execute(_request(tmp_path))
    assert exc.value.category is M10CompositionFailureCategory.PROJECTION


def test_canonical_validator_mutation_is_sanitized(tmp_path):
    confluence, git = _handoffs()
    from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
    canonical = FoundationSchemaValidator()
    canonical.validate_record = lambda schema_name, record: record.__setitem__("canonical_mutation", True)
    with pytest.raises(M10CompositionFailure) as exc:
        ComposeM10Snapshot(confluence_adapter=Adapter(confluence), git_adapter=Adapter(git), schema_validator=type("V", (), {"validate_record": lambda self, name, record: None})(), canonical_schema_validator=canonical).execute(_request(tmp_path))
    assert exc.value.category is M10CompositionFailureCategory.PROJECTION


def test_validator_exception_is_sanitized_projection_failure(tmp_path):
    confluence, git = _handoffs()
    class ExplodingValidator:
        def validate_record(self, schema_name, record): raise RuntimeError("secret schema internals")
    with pytest.raises(M10CompositionFailure) as exc:
        ComposeM10Snapshot(confluence_adapter=Adapter(confluence), git_adapter=Adapter(git), schema_validator=ExplodingValidator()).execute(_request(tmp_path))
    assert exc.value.category is M10CompositionFailureCategory.PROJECTION
    assert "secret" not in str(exc.value)


def test_shared_validator_rejects_extra_record_field(tmp_path):
    confluence, git = _handoffs()
    forged = {**confluence.documents[0], "forbidden": True}
    from knowledgenexus.foundation.domain.models.m10_composition import M10ConfluenceHandoff
    bad = M10ConfluenceHandoff(confluence.run_id, confluence.generation_id, confluence.source_version, (forged,), confluence.chunks, confluence.relations, confluence.acl, (), (), (), confluence.raw_artifact_identity)
    with pytest.raises(M10CompositionFailure) as exc:
        ComposeM10Snapshot(confluence_adapter=Adapter(bad), git_adapter=Adapter(git)).execute(_request(tmp_path))
    assert exc.value.category is M10CompositionFailureCategory.PROJECTION


def test_forged_result_fields_fail_closed(tmp_path):
    confluence, git = _handoffs()
    result = ComposeM10Snapshot(confluence_adapter=Adapter(confluence), git_adapter=Adapter(git), schema_validator=type("V", (), {"validate_record": lambda self, name, record: None})()).execute(_request(tmp_path))
    forged = object.__new__(type(result))
    object.__setattr__(forged, "projection", result.projection)
    object.__setattr__(forged, "failure_category", None)
    object.__setattr__(forged, "extra", True)
    with pytest.raises((TypeError, ValueError)):
        type(result).__post_init__(forged)

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import ContextManager, Protocol

from knowledgenexus.foundation.domain.models.confluence_crawl_run import (
    CrawlRunId,
    CrawlRunSnapshot,
    CrawlSessionId,
    _validated_run_id,
)
from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceSourceConfig,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_fingerprint import (
    _build_effective_crawl_input,
)
from knowledgenexus.foundation.ports.confluence_checkpoint_state_port import (
    ConfluenceCheckpointStatePort,
)


@dataclass(frozen=True, repr=False)
class StartNewRunRequest:
    workspace: Path
    endpoint_url: str
    source_config: ConfluenceSourceConfig
    reliability_profile: Mapping[str, object]

    def __post_init__(self) -> None:
        _validate_request_fields(
            self,
            self.workspace,
            self.endpoint_url,
            self.source_config,
            self.reliability_profile,
        )

    def __repr__(self) -> str:
        return "StartNewRunRequest()"


@dataclass(frozen=True, repr=False)
class ResumeExplicitRunRequest:
    workspace: Path
    run_id: CrawlRunId
    endpoint_url: str
    source_config: ConfluenceSourceConfig
    reliability_profile: Mapping[str, object]

    def __post_init__(self) -> None:
        _validate_request_fields(
            self,
            self.workspace,
            self.endpoint_url,
            self.source_config,
            self.reliability_profile,
        )
        try:
            _validated_run_id(self.run_id)
        except (TypeError, ValueError):
            raise ValueError("invalid checkpoint run request") from None

    def __repr__(self) -> str:
        return "ResumeExplicitRunRequest()"


@dataclass(frozen=True, repr=False)
class ActivateRawGenerationRequest:
    workspace: Path
    run_id: CrawlRunId
    endpoint_url: str
    source_config: ConfluenceSourceConfig
    reliability_profile: Mapping[str, object]

    def __post_init__(self) -> None:
        _validate_request_fields(
            self,
            self.workspace,
            self.endpoint_url,
            self.source_config,
            self.reliability_profile,
        )
        try:
            _validated_run_id(self.run_id)
        except (TypeError, ValueError):
            raise ValueError("invalid checkpoint run request") from None

    def __repr__(self) -> str:
        return "ActivateRawGenerationRequest()"


@dataclass(frozen=True, repr=False)
class ResumeUniqueIncompleteRunRequest:
    workspace: Path
    endpoint_url: str
    source_config: ConfluenceSourceConfig
    reliability_profile: Mapping[str, object]

    def __post_init__(self) -> None:
        _validate_request_fields(
            self,
            self.workspace,
            self.endpoint_url,
            self.source_config,
            self.reliability_profile,
        )

    def __repr__(self) -> str:
        return "ResumeUniqueIncompleteRunRequest()"


def _validate_request_fields(
    target: object,
    workspace: object,
    endpoint_url: object,
    source_config: object,
    reliability_profile: object,
) -> None:
    if not isinstance(workspace, Path) or type(endpoint_url) is not str or not endpoint_url:
        raise ValueError("invalid checkpoint run request")
    if type(source_config) is not ConfluenceSourceConfig:
        raise TypeError("invalid checkpoint run request")
    if not isinstance(reliability_profile, Mapping):
        raise TypeError("invalid checkpoint run request")
    try:
        snapshot = dict(reliability_profile)
    except (TypeError, ValueError):
        raise ValueError("invalid checkpoint run request") from None
    object.__setattr__(
        # The caller's mapping must not remain mutable after construction.
        # Dataclass instances are frozen, so replace the field explicitly.
        target,
        "reliability_profile",
        MappingProxyType(snapshot),
    )
    try:
        _build_effective_crawl_input(endpoint_url, source_config, snapshot)
    except (TypeError, ValueError):
        raise ValueError("invalid checkpoint run request") from None


class CheckpointRunSelectionFailureCategory(str):
    RUN_OPERATION_INVALID = "run_operation_invalid"
    RUN_NOT_FOUND = "run_not_found"
    RUN_NOT_RESUMABLE = "run_not_resumable"
    RUN_MATCH_AMBIGUOUS = "run_match_ambiguous"
    INCOMPLETE_RUN_CONFLICT = "incomplete_run_conflict"


@dataclass(frozen=True, repr=False)
class CheckpointRunSelectionFailure:
    category: str

    def __post_init__(self) -> None:
        if self.category not in {
            CheckpointRunSelectionFailureCategory.RUN_OPERATION_INVALID,
            CheckpointRunSelectionFailureCategory.RUN_NOT_FOUND,
            CheckpointRunSelectionFailureCategory.RUN_NOT_RESUMABLE,
            CheckpointRunSelectionFailureCategory.RUN_MATCH_AMBIGUOUS,
            CheckpointRunSelectionFailureCategory.INCOMPLETE_RUN_CONFLICT,
        }:
            raise ValueError("invalid run selection failure")

    def __repr__(self) -> str:
        return "CheckpointRunSelectionFailure()"


@dataclass(frozen=True, repr=False)
class CheckpointRunInventoryComplete:
    snapshot: CrawlRunSnapshot

    def __post_init__(self) -> None:
        if type(self.snapshot) is not CrawlRunSnapshot:
            raise TypeError("invalid inventory-complete outcome")

    def __repr__(self) -> str:
        return "CheckpointRunInventoryComplete()"


class CheckpointRunActivation(ConfluenceCheckpointStatePort, Protocol):
    snapshot: CrawlRunSnapshot
    session_id: CrawlSessionId


CheckpointRunOutcome = (
    CheckpointRunActivation
    | CheckpointRunInventoryComplete
    | CheckpointRunSelectionFailure
)


class ConfluenceCheckpointRunPort(Protocol):
    def start_new_run(
        self, request: StartNewRunRequest
    ) -> ContextManager[CheckpointRunOutcome]: ...

    def resume_explicit_run_id(
        self, request: ResumeExplicitRunRequest
    ) -> ContextManager[CheckpointRunOutcome]: ...

    def resume_unique_incomplete_run(
        self, request: ResumeUniqueIncompleteRunRequest
    ) -> ContextManager[CheckpointRunOutcome]: ...

    def activate_raw_generation(
        self, request: ActivateRawGenerationRequest
    ) -> ContextManager[CheckpointRunOutcome]: ...

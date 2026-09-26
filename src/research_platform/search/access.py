"""Service-layer policy for private inspection and public passage rights."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EvidenceAccessProfile(str, Enum):
    """Server-selected evidence access profile; never selected by a request."""

    DISABLED = "disabled"
    TRUSTED_PRIVATE_LOCAL = "trusted_private_local"


class EvidenceAccessDenied(PermissionError):
    """The configured access profile or source rights do not permit inspection."""


@dataclass(frozen=True)
class EvidencePermissionEvidence:
    """Permission flags from both the artifact association and rights review."""

    artifact_storage_permitted: bool
    artifact_indexing_permitted: bool
    review_storage_permitted: bool
    review_indexing_permitted: bool
    artifact_passage_display_permitted: bool
    review_passage_display_permitted: bool

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, bool)
            for value in (
                self.artifact_storage_permitted,
                self.artifact_indexing_permitted,
                self.review_storage_permitted,
                self.review_indexing_permitted,
                self.artifact_passage_display_permitted,
                self.review_passage_display_permitted,
            )
        ):
            raise ValueError("permission decisions must be booleans")

    @property
    def permits_private_inspection(self) -> bool:
        return all(
            (
                self.artifact_storage_permitted,
                self.artifact_indexing_permitted,
                self.review_storage_permitted,
                self.review_indexing_permitted,
            )
        )


@dataclass(frozen=True)
class EvidenceAccessPolicy:
    """An immutable execution policy created from trusted server configuration."""

    profile: EvidenceAccessProfile

    def __post_init__(self) -> None:
        if not isinstance(self.profile, EvidenceAccessProfile):
            raise ValueError("profile must be an EvidenceAccessProfile")

    @classmethod
    def from_setting(cls, value: str) -> EvidenceAccessPolicy:
        try:
            profile = EvidenceAccessProfile(value)
        except ValueError:
            raise ValueError("unsupported evidence access profile") from None
        return cls(profile=profile)

    def can_inspect_private(self, permissions: EvidencePermissionEvidence) -> bool:
        return (
            self.profile is EvidenceAccessProfile.TRUSTED_PRIVATE_LOCAL
            and permissions.permits_private_inspection
        )

    def require_private_inspection(
        self, permissions: EvidencePermissionEvidence
    ) -> None:
        if not self.can_inspect_private(permissions):
            raise EvidenceAccessDenied("private evidence inspection is not permitted")

    def can_display_public(self, _permissions: EvidencePermissionEvidence) -> bool:
        """Public passage output is outside Phase 2, even if a record allows it."""
        return False

    def require_public_display(self, _permissions: EvidencePermissionEvidence) -> None:
        raise EvidenceAccessDenied("public passage display is not available in Phase 2")

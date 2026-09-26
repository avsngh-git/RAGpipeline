"""Behavioral checks for private evidence access and public-display boundaries."""

import pytest

from research_platform.search.access import (
    EvidenceAccessDenied,
    EvidenceAccessPolicy,
    EvidenceAccessProfile,
    EvidencePermissionEvidence,
)


def permissions(**changes: bool) -> EvidencePermissionEvidence:
    values = {
        "artifact_storage_permitted": True,
        "artifact_indexing_permitted": True,
        "review_storage_permitted": True,
        "review_indexing_permitted": True,
        "artifact_passage_display_permitted": False,
        "review_passage_display_permitted": False,
    }
    values.update(changes)
    return EvidencePermissionEvidence(**values)


def test_trusted_local_profile_allows_private_storage_and_indexing_rights() -> None:
    policy = EvidenceAccessPolicy(EvidenceAccessProfile.TRUSTED_PRIVATE_LOCAL)
    source_rights = permissions()

    assert policy.can_inspect_private(source_rights)
    policy.require_private_inspection(source_rights)
    assert not policy.can_display_public(source_rights)


def test_private_inspection_requires_every_source_and_review_right() -> None:
    policy = EvidenceAccessPolicy(EvidenceAccessProfile.TRUSTED_PRIVATE_LOCAL)
    for denied_right in (
        "artifact_storage_permitted",
        "artifact_indexing_permitted",
        "review_storage_permitted",
        "review_indexing_permitted",
    ):
        source_rights = permissions(**{denied_right: False})
        assert not policy.can_inspect_private(source_rights)
        with pytest.raises(EvidenceAccessDenied):
            policy.require_private_inspection(source_rights)


def test_disabled_profile_denies_private_inspection() -> None:
    policy = EvidenceAccessPolicy(EvidenceAccessProfile.DISABLED)

    assert not policy.can_inspect_private(permissions())
    with pytest.raises(EvidenceAccessDenied):
        policy.require_private_inspection(permissions())


def test_public_passage_display_remains_disabled_even_if_a_record_allows_it() -> None:
    policy = EvidenceAccessPolicy(EvidenceAccessProfile.TRUSTED_PRIVATE_LOCAL)
    source_rights = permissions(
        artifact_passage_display_permitted=True,
        review_passage_display_permitted=True,
    )

    assert not policy.can_display_public(source_rights)
    with pytest.raises(EvidenceAccessDenied, match="not available in Phase 2"):
        policy.require_public_display(source_rights)


def test_access_profile_must_be_server_selected_and_supported() -> None:
    assert (
        EvidenceAccessPolicy.from_setting("trusted_private_local").profile
        is EvidenceAccessProfile.TRUSTED_PRIVATE_LOCAL
    )
    with pytest.raises(ValueError, match="unsupported evidence access profile"):
        EvidenceAccessPolicy.from_setting("public")
    with pytest.raises(ValueError, match="profile must be an EvidenceAccessProfile"):
        EvidenceAccessPolicy(profile="trusted_private_local")  # type: ignore[arg-type]

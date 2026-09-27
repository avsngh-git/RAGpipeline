"""Stable, dependency-light errors shared by search composition and HTTP mapping."""


class IncompatibleRetrievalProfile(ValueError):
    """The requested profile, mode, snapshot or runtime stage does not agree."""


class SearchDependencyUnavailable(RuntimeError):
    """A required local profile asset or dependency is unavailable."""


class RetrievalExecutionFailure(RuntimeError):
    """A required retrieval stage failed without producing a complete result."""

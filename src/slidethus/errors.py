class SlidethusError(Exception):
    """Base exception for deterministic Slidethus failures."""


class WorkspaceError(SlidethusError):
    """Raised when a workspace is missing, unsafe, or inconsistent."""


class SchemaError(SlidethusError):
    """Raised when a schema registry cannot be loaded."""


class StateTransitionError(SlidethusError):
    """Raised when a project phase transition is invalid."""


class ArtifactError(SlidethusError):
    """Raised when an artifact operation cannot be completed safely."""


class ArtifactConflictError(ArtifactError):
    """Raised when optimistic locking detects a concurrent or manual edit."""


class MigrationError(ArtifactError):
    """Raised when no safe schema migration path exists."""


class RecoveryError(ArtifactError):
    """Raised when an interrupted transaction cannot be recovered."""


class GateError(SlidethusError):
    """Raised when a gate result or phase advance violates gate policy."""

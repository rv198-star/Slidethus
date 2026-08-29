class SlidethusError(Exception):
    """Base exception for deterministic Slidethus failures."""


class WorkspaceError(SlidethusError):
    """Raised when a workspace is missing, unsafe, or inconsistent."""


class SourceIngestionError(SlidethusError):
    """Raised when a source cannot be identified, parsed, or persisted safely."""


class UnsupportedSourceError(SourceIngestionError):
    """Raised when no admitted parser supports the detected source format."""


class SourceCapabilityError(SourceIngestionError):
    """Raised when an admitted parser lacks an optional local dependency."""


class ResearchError(SlidethusError):
    """Base exception for research planning, execution, cache, and lineage failures."""


class ResearchPlanningError(ResearchError):
    """Raised when a bounded research plan cannot be formed from current artifacts."""


class ResearchRuntimeError(ResearchError):
    """Raised when persisted research runtime state is missing, unsafe, or inconsistent."""


class ResearchCacheError(ResearchRuntimeError):
    """Raised when research cache lineage cannot be validated safely."""


class ResearchProviderError(ResearchError):
    """Raised after a provider failure has been checkpointed for later resume."""


class ResearchOfflineError(ResearchError):
    """Raised by an explicitly offline provider instead of fabricating results."""


class EvidenceError(SlidethusError):
    """Base exception for Evidence candidate, materialization, and adjudication failures."""


class EvidenceMaterializationError(EvidenceError):
    """Raised when a source or Research Result cannot become an auditable Evidence candidate."""


class EvidenceAdjudicationError(EvidenceError):
    """Raised when Evidence policy cannot be decided safely or consistently."""


class EvidenceBindingError(EvidenceError):
    """Raised when Outline/Block Evidence binding cannot be analyzed safely."""


class EvidenceGapError(EvidenceBindingError):
    """Raised when an Evidence Gap report is missing, unsafe, or inconsistent."""


class M2ApplicationError(SlidethusError):
    """Raised when M2 application orchestration cannot continue safely."""


class M2CapabilityError(M2ApplicationError):
    """Raised when required M2 host or policy capability is unavailable."""


class M2ApplicationReportError(M2ApplicationError):
    """Raised when a persisted M2 Application Report is unsafe or inconsistent."""


class PlanningError(SlidethusError):
    """Base exception for M3 narrative and planning failures."""


class PlanningLimitError(PlanningError):
    """Raised when M3 planning limits exceed admitted deterministic bounds."""


class BriefCompletionError(PlanningError):
    """Raised when Project Brief completion cannot proceed safely."""


class NarrativePlanningError(PlanningError):
    """Raised when Narrative Blueprint generation or validation fails."""


class OutlinePlanningError(PlanningError):
    """Raised when Deck Outline generation or sticky-note operations fail."""


class SlideSpecPlanningError(PlanningError):
    """Raised when Slide Specifications cannot be generated or repaired safely."""


class LayoutPlanningError(PlanningError):
    """Raised when Layout Plans violate geometry, coverage, or capacity contracts."""


class PlanningReviewError(PlanningError):
    """Raised when a Planning Review fact is missing, unsafe, or inconsistent."""


class M3ApplicationError(PlanningError):
    """Raised when integrated M3 orchestration cannot continue safely."""


class M3ApplicationReportError(M3ApplicationError):
    """Raised when a persisted M3 Application Report is unsafe or inconsistent."""


class RenderingError(SlidethusError):
    """Base exception for M4 visual-system compilation and rendering failures."""


class RenderCompileError(RenderingError):
    """Raised when current planning artifacts cannot compile into renderer input safely."""


class RenderBackendError(RenderingError):
    """Raised when a concrete Production render backend cannot produce a valid output."""


class RenderCapabilityError(RenderingError):
    """Raised when a requested renderer or preview capability is unavailable on the host."""


class RenderManifestError(RenderingError):
    """Raised when persisted render lineage is missing, unsafe, or inconsistent."""


class RenderAssetError(RenderingError):
    """Raised when a renderer asset is missing, unsafe, unlicensed, or inconsistent."""


class FontResolutionError(RenderingError):
    """Raised when an admitted font family cannot be resolved consistently."""


class ReviewError(SlidethusError):
    """Base exception for M5 independent review and repair failures."""


class DeterministicReviewError(ReviewError):
    """Raised when an M5 deterministic review fact is unsafe or inconsistent."""


class SemanticReviewError(ReviewError):
    """Raised when an M5 semantic review proposal or persisted fact is inconsistent."""


class VisualReviewError(ReviewError):
    """Raised when an M5 visual review proposal or persisted fact is inconsistent."""


class ReviewRepairError(ReviewError):
    """Raised when an M5 repair plan or bounded repair execution is inconsistent."""


class ReviewRegressionError(ReviewError):
    """Raised when an M5 post-repair regression fact is inconsistent."""


class StageReviewError(ReviewError):
    """Raised when a retrospective Stage AI Review fact is unsafe or inconsistent."""


class ReviewSynthesisError(ReviewError):
    """Raised when whole-attempt review attribution/synthesis is unsafe or inconsistent."""


class M5ApplicationError(ReviewError):
    """Raised when integrated M5 review/repair orchestration cannot continue safely."""


class WorkflowError(SlidethusError):
    """Base exception for M6 product workflow failures."""


class WorkflowApplicationError(WorkflowError):
    """Raised when a workflow request/report is unsafe or inconsistent."""


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

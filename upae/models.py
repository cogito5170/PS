"""Core data model: sources, passages, propositions, evidence, relations,
assessments, issues and derivations are distinct objects linked by stable IDs.

See docs/DATA_MODEL.md for field semantics, validation rules and invariants.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from typing import Any, Optional

SCHEMA_VERSION = "1.2"
PROCESSING_VERSION = "upae-0.1.0"


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class SourceKind(StrEnum):
    BLOG = "blog"
    NEWS = "news"
    SOCIAL = "social"
    PAPER = "paper"
    TEXTBOOK = "textbook"
    BOOK = "book"
    REPORT = "report"
    DATASET = "dataset"
    WEB = "web"
    OTHER = "other"


class ClaimType(StrEnum):
    EMPIRICAL = "empirical"
    STATISTICAL = "statistical"
    CAUSAL = "causal"
    CORRELATIONAL = "correlational"
    DEFINITION = "definition"
    OPINION = "opinion"
    NORMATIVE = "normative"
    PREDICTION = "prediction"
    HYPOTHESIS = "hypothesis"
    OBSERVATION = "observation"
    MATHEMATICAL = "mathematical"
    QUOTATION = "quotation"
    COMPOUND = "compound"


# Claim types whose truth is not assessed against empirical evidence.
NON_TRUTH_APT = {ClaimType.OPINION, ClaimType.NORMATIVE}


class Modality(StrEnum):
    ASSERTED = "asserted"      # stated as fact by the author
    POSSIBLE = "possible"      # hedged: may / might / could / suggests
    PROBABLE = "probable"      # likely / probably
    NECESSARY = "necessary"    # must (epistemic) / always
    PREDICTED = "predicted"    # will / is expected to
    REPORTED = "reported"      # attributed to someone other than the author
    QUESTIONED = "questioned"  # posed as a question


class Polarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class RelationType(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    ENTAILS = "ENTAILS"
    REQUIRES = "REQUIRES"
    CAUSES = "CAUSES"
    CORRELATES_WITH = "CORRELATES_WITH"
    QUALIFIES = "QUALIFIES"
    REFINES = "REFINES"
    CORRECTS = "CORRECTS"
    DUPLICATES = "DUPLICATES"
    DERIVED_FROM = "DERIVED_FROM"
    DIFFERS_IN_SCOPE = "DIFFERS_IN_SCOPE"


UNDIRECTED_RELATIONS = {
    RelationType.CONTRADICTS,
    RelationType.CORRELATES_WITH,
    RelationType.DUPLICATES,
    RelationType.DIFFERS_IN_SCOPE,
}


class ReviewStatus(StrEnum):
    AUTO_DETERMINISTIC = "auto_deterministic"  # produced by a deterministic rule
    AUTO_MODEL = "auto_model"                  # produced by a model; never "verified"
    ASSERTED_BY_SOURCE = "asserted_by_source"  # the source states the relation; not verified
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"                    # human confirmed
    REJECTED = "rejected"                      # human rejected (kept for audit)


class Status(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    RETRACTED = "RETRACTED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class Stance(StrEnum):
    SUPPORTS = "supports"
    CHALLENGES = "challenges"


class EvidenceBasis(StrEnum):
    EXPERIMENTAL = "experimental"
    REVIEW = "review"
    DATASET = "dataset"
    OBSERVATIONAL = "observational"
    SURVEY = "survey"
    DOCUMENTARY = "documentary"
    SECONDARY = "secondary"
    EXPERT_OPINION = "expert_opinion"
    ANECDOTAL = "anecdotal"
    LOGICAL = "logical"
    UNSPECIFIED = "unspecified"


class IssueCategory(StrEnum):
    NUMERICAL_INCONSISTENCY = "NUMERICAL_INCONSISTENCY"
    CATEGORICAL_CONFLICT = "CATEGORICAL_CONFLICT"
    TEMPORAL_DISAGREEMENT = "TEMPORAL_DISAGREEMENT"
    DEFINITION_CONFLICT = "DEFINITION_CONFLICT"
    INTERNAL_INCONSISTENCY = "INTERNAL_INCONSISTENCY"
    ARITHMETIC_ERROR = "ARITHMETIC_ERROR"
    INVALID_INFERENCE = "INVALID_INFERENCE"
    UNSUPPORTED_CAUSAL_CLAIM = "UNSUPPORTED_CAUSAL_CLAIM"
    MISLEADING_QUOTATION = "MISLEADING_QUOTATION"
    TRANSLATION_DISCREPANCY = "TRANSLATION_DISCREPANCY"
    MISSING_CONDITION = "MISSING_CONDITION"
    DEPENDENT_CORROBORATION = "DEPENDENT_CORROBORATION"
    RETRACTED_SOURCE_DEPENDENCY = "RETRACTED_SOURCE_DEPENDENCY"
    AMBIGUOUS_PROPOSITION = "AMBIGUOUS_PROPOSITION"
    EXTRACTION_UNCERTAIN = "EXTRACTION_UNCERTAIN"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    PREDICTION_PAST_DUE = "PREDICTION_PAST_DUE"


class FindingClass(StrEnum):
    CONFIRMED_ERROR = "CONFIRMED_ERROR"            # deterministic proof (e.g. arithmetic)
    PROBABLE_ERROR = "PROBABLE_ERROR"              # strong but defeasible signal
    UNRESOLVED_CONTRADICTION = "UNRESOLVED_CONTRADICTION"
    SUSPICIOUS_CLAIM = "SUSPICIOUS_CLAIM"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    LIMITATION = "LIMITATION"                      # processing / access limitation


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_ORDER = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}
RED_CLASSES = {
    FindingClass.CONFIRMED_ERROR,
    FindingClass.PROBABLE_ERROR,
    FindingClass.UNRESOLVED_CONTRADICTION,
}
RED_MIN_CONFIDENCE = 0.5


# --------------------------------------------------------------------------- helpers

def _to_plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(v) for v in value]
    return value


class Record:
    """Mixin: plain-dict (de)serialisation for dataclasses with enum fields."""

    def to_dict(self) -> dict:
        return _to_plain(asdict(self))  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, data: dict):
        kwargs = {}
        for f in fields(cls):  # type: ignore[arg-type]
            if f.name not in data:
                continue
            value = data[f.name]
            conv = _CONVERTERS.get((cls.__name__, f.name))
            kwargs[f.name] = conv(value) if (conv and value is not None) else value
        return cls(**kwargs)


# --------------------------------------------------------------------------- objects

@dataclass
class Quantity(Record):
    value: float
    unit: Optional[str] = None            # unit as written ("°F", "km", "%")
    raw: str = ""                         # original text span
    norm_value: Optional[float] = None    # value in canonical unit
    norm_unit: Optional[str] = None       # canonical unit ("degC", "m", "percent")
    dimension: Optional[str] = None       # "temperature", "length", "ratio", "currency:USD"
    kind: str = "level"                   # level | change | change_pp | from_to | year
    approximate: bool = False
    from_value: Optional[float] = None    # for from_to quantities
    to_value: Optional[float] = None


@dataclass
class Scope(Record):
    time: Optional[str] = None            # as written
    time_norm: Optional[list] = None      # [start_year, end_year]
    time_resolved: Optional[list] = None  # [start, end] ISO dates, anchored to publication date
    location: Optional[str] = None
    population: Optional[str] = None
    conditions: list = field(default_factory=list)
    units: Optional[str] = None
    definitions: dict = field(default_factory=dict)  # term -> definition proposition id

    def is_empty(self) -> bool:
        return not (self.time or self.location or self.population or self.conditions)


@dataclass
class Attribution(Record):
    speaker: Optional[str] = None         # who asserts the content (None = document author)
    kind: str = "author"                  # author | reported | quoted
    quote: Optional[str] = None           # verbatim quotation if quoted
    origin_source_id: Optional[str] = None  # source in corpus the claim is attributed to


@dataclass
class Extraction(Record):
    method: str                           # e.g. "rule:copula@1" or "model:<provider>"
    version: str = PROCESSING_VERSION
    confidence: float = 0.0
    review_required: bool = False
    notes: list = field(default_factory=list)
    deterministic: bool = True


@dataclass
class Passage(Record):
    """Verbatim span of an archived source document (the evidence archive)."""
    id: str
    source_id: str
    text: str
    char_start: int
    char_end: int
    language: str = "und"
    language_confidence: float = 0.0
    page: Optional[int] = None
    section: Optional[str] = None
    paragraph_index: int = 0


@dataclass
class Source(Record):
    id: str
    key: str                              # caller-supplied identity (file name / doc key)
    kind: SourceKind = SourceKind.OTHER
    title: Optional[str] = None
    author: Optional[str] = None
    publisher: Optional[str] = None
    published: Optional[str] = None
    url: Optional[str] = None
    canonical_url: Optional[str] = None
    doi: Optional[str] = None
    isbn: Optional[str] = None
    language: str = "und"
    retrieved_at: Optional[str] = None
    content_hash: Optional[str] = None
    version: Optional[str] = None
    license: Optional[str] = None
    access_status: str = "accessible"     # accessible | unavailable | restricted | unsupported_format
    access_note: Optional[str] = None
    retracted: bool = False
    basis: Optional[EvidenceBasis] = None # evidence type the document reports for itself
    reproduces: Optional[str] = None      # source id this document copies / syndicates
    translation_of: Optional[str] = None  # source id this document translates
    cites: list = field(default_factory=list)
    independence_group: Optional[str] = None
    duplicate_of: Optional[str] = None
    synthetic: bool = False
    connector: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Proposition(Record):
    id: str
    fingerprint: str
    text: str                             # compact normalised statement
    subject: str
    predicate: str
    object: Optional[str]
    claim_type: ClaimType
    surface: dict = field(default_factory=dict)  # original (un-normalised) s/p/o strings
    modality: Modality = Modality.ASSERTED
    polarity: Polarity = Polarity.POSITIVE
    direction: int = 0                    # +1 increase, -1 decrease, 0 none
    quantity: Optional[Quantity] = None
    quantifier: Optional[str] = None      # all | most | many | some | few | none
    scope: Scope = field(default_factory=Scope)
    attribution: Attribution = field(default_factory=Attribution)
    source_refs: list = field(default_factory=list)
    passage_id: Optional[str] = None
    quote: str = ""                       # verbatim sentence from the passage
    quote_span: Optional[list] = None     # [start, end] offsets inside passage text
    language: str = "en"
    original_text: Optional[str] = None   # original-language text if extracted from a translation
    evidence_refs: list = field(default_factory=list)
    relation_refs: list = field(default_factory=list)
    issue_refs: list = field(default_factory=list)
    components: list = field(default_factory=list)  # child ids of a compound proposition
    parent_id: Optional[str] = None
    stated_basis: Optional[EvidenceBasis] = None    # basis cue in the source text
    extraction: Extraction = field(default_factory=lambda: Extraction(method="unknown"))
    version: int = 1
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    created_at: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    @property
    def is_truth_apt(self) -> bool:
        return self.claim_type not in NON_TRUTH_APT


@dataclass
class Evidence(Record):
    id: str
    proposition_id: str                   # the proposition this evidence bears on
    stance: Stance
    source_id: str
    passage_id: Optional[str]
    via_proposition: Optional[str]        # the proposition that constitutes the evidence
    basis: EvidenceBasis = EvidenceBasis.UNSPECIFIED
    primary: bool = False
    directness: str = "direct"            # direct | indirect
    independence_group: Optional[str] = None
    temporal_relevance: str = "unknown"   # same_period | different_period | unknown
    conflicts_of_interest: list = field(default_factory=list)
    missing_method_details: list = field(default_factory=list)
    strength: float = 0.0                 # transparent formula, see EVIDENCE_POLICY.md
    strength_terms: dict = field(default_factory=dict)
    method: str = ""


@dataclass
class Relation(Record):
    id: str
    type: RelationType
    source: str                           # proposition id (tail)
    target: str                           # proposition id (head)
    directed: bool = True
    rationale: str = ""
    evidence_refs: list = field(default_factory=list)  # passage ids
    confidence: float = 0.0
    review_status: ReviewStatus = ReviewStatus.AUTO_DETERMINISTIC
    method: str = ""
    dimensions: list = field(default_factory=list)       # differing / conflicting dimensions
    assumptions: list = field(default_factory=list)      # assumptions needed for the relation


@dataclass
class Transition(Record):
    from_status: Status
    to_status: Status
    actor: str
    reason: str
    at: Optional[str] = None


@dataclass
class Assessment(Record):
    id: str
    proposition_id: str
    status: Status = Status.UNVERIFIED
    confidence: Optional[float] = None
    rationale: str = ""
    belnap: str = "N"                     # N (none) | T | F | B (both)
    support_strength: float = 0.0
    challenge_strength: float = 0.0
    support_groups: list = field(default_factory=list)
    challenge_groups: list = field(default_factory=list)
    dependent_copies: int = 0
    criteria: dict = field(default_factory=dict)
    review_required: bool = False
    review_triggers: list = field(default_factory=list)
    history: list = field(default_factory=list)


@dataclass
class Issue(Record):
    id: str
    category: IssueCategory
    finding_class: FindingClass
    severity: Severity
    confidence: float
    affected: list                        # proposition / source ids
    conflicting: list = field(default_factory=list)
    reason: str = ""
    evidence: list = field(default_factory=list)       # passage / evidence ids
    resolution: str = ""                  # what information would resolve the issue
    dimensions: list = field(default_factory=list)
    assumptions: list = field(default_factory=list)
    detector: str = ""
    deterministic: bool = True
    red: bool = False
    details: dict = field(default_factory=dict)

    def red_for(self, ref: str) -> bool:
        """Is this issue red *for this proposition*?  When evidence has singled out
        the probable-error side of a contradiction, the better-supported side is
        listed as affected but not flagged red."""
        if not self.red:
            return False
        weak = self.details.get("probable_error_on")
        return weak is None or ref in weak

    def compute_red(self) -> bool:
        self.red = (
            self.finding_class in RED_CLASSES and self.confidence >= RED_MIN_CONFIDENCE
        ) or (
            SEVERITY_ORDER[self.severity] >= SEVERITY_ORDER[Severity.HIGH]
            and self.confidence >= RED_MIN_CONFIDENCE
        )
        return self.red


@dataclass
class Derivation(Record):
    id: str
    conclusion: str
    premises: list
    marker: str                           # textual inference marker ("therefore")
    validity: str = "unknown"             # valid | invalid | unknown
    checks: list = field(default_factory=list)
    method: str = "rule:inference-marker@1"


@dataclass
class Omission(Record):
    proposition_id: str
    decision: str                         # merged | hidden_low_priority | summarized
    reason: str
    into: Optional[str] = None
    score: Optional[float] = None


_CONVERTERS = {
    ("Source", "kind"): SourceKind,
    ("Source", "basis"): EvidenceBasis,
    ("Proposition", "claim_type"): ClaimType,
    ("Proposition", "modality"): Modality,
    ("Proposition", "polarity"): Polarity,
    ("Proposition", "quantity"): Quantity.from_dict,
    ("Proposition", "scope"): Scope.from_dict,
    ("Proposition", "attribution"): Attribution.from_dict,
    ("Proposition", "extraction"): Extraction.from_dict,
    ("Proposition", "stated_basis"): EvidenceBasis,
    ("Evidence", "stance"): Stance,
    ("Evidence", "basis"): EvidenceBasis,
    ("Relation", "type"): RelationType,
    ("Relation", "review_status"): ReviewStatus,
    ("Transition", "from_status"): Status,
    ("Transition", "to_status"): Status,
    ("Assessment", "status"): Status,
    ("Issue", "category"): IssueCategory,
    ("Issue", "finding_class"): FindingClass,
    ("Issue", "severity"): Severity,
}

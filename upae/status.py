"""Assessment status semantics and the allowed-transition table.

Meaning of each status (also in docs/DATA_MODEL.md §6):

UNVERIFIED            No evidence in the corpus beyond the assertion itself.
SUPPORTED             Independent support S ≥ τ and challenge C < S/2.
CONTRADICTED          Independent challenge C ≥ τ and support S < C/2, or a
                      deterministic proof of error (arithmetic / equation).
CONFLICTING_EVIDENCE  Both support and challenge present and neither dominates.
INSUFFICIENT_EVIDENCE Evidence exists but only from dependent copies, or its
                      independent strength is below τ.
OUT_OF_SCOPE          Not empirically assessable (opinion, normative statement).
RETRACTED             The proposition comes from a retracted source.
HUMAN_REVIEW_REQUIRED A review trigger fired (uncertain extraction that other
                      findings depend on, model-only judgment, mistranslation).

Transitions carry an actor: "system" transitions may be performed by an
automatic re-analysis; "human" transitions require a reviewer decision.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .models import Assessment, Status, Transition

S = Status
_ALL = set(Status)

# from-status -> {to-status: minimum actor}
TRANSITIONS: dict[Status, dict[Status, str]] = {
    S.UNVERIFIED: {t: "system" for t in _ALL - {S.UNVERIFIED}},
    S.SUPPORTED: {S.CONFLICTING_EVIDENCE: "system", S.CONTRADICTED: "system",
                  S.INSUFFICIENT_EVIDENCE: "system", S.UNVERIFIED: "system",
                  S.RETRACTED: "system", S.HUMAN_REVIEW_REQUIRED: "system",
                  S.OUT_OF_SCOPE: "human"},
    S.CONTRADICTED: {S.CONFLICTING_EVIDENCE: "system", S.SUPPORTED: "system",
                     S.INSUFFICIENT_EVIDENCE: "system", S.UNVERIFIED: "system",
                     S.RETRACTED: "system", S.HUMAN_REVIEW_REQUIRED: "system",
                     S.OUT_OF_SCOPE: "human"},
    S.CONFLICTING_EVIDENCE: {S.SUPPORTED: "system", S.CONTRADICTED: "system",
                             S.INSUFFICIENT_EVIDENCE: "system", S.UNVERIFIED: "system",
                             S.RETRACTED: "system", S.HUMAN_REVIEW_REQUIRED: "system",
                             S.OUT_OF_SCOPE: "human"},
    S.INSUFFICIENT_EVIDENCE: {S.SUPPORTED: "system", S.CONTRADICTED: "system",
                              S.CONFLICTING_EVIDENCE: "system", S.UNVERIFIED: "system",
                              S.RETRACTED: "system", S.HUMAN_REVIEW_REQUIRED: "system",
                              S.OUT_OF_SCOPE: "human"},
    # claim type is fixed per proposition version; leaving OUT_OF_SCOPE needs a human
    # (or a new proposition version, which starts at UNVERIFIED).
    S.OUT_OF_SCOPE: {S.RETRACTED: "system", S.HUMAN_REVIEW_REQUIRED: "system",
                     **{t: "human" for t in (S.UNVERIFIED, S.SUPPORTED, S.CONTRADICTED,
                                             S.CONFLICTING_EVIDENCE, S.INSUFFICIENT_EVIDENCE)}},
    # a retraction is only lifted by a human decision (e.g. retraction notice withdrawn)
    S.RETRACTED: {t: "human" for t in _ALL - {S.RETRACTED}},
    # the system may leave review only when no review trigger remains (checked by caller)
    S.HUMAN_REVIEW_REQUIRED: {t: "system" for t in _ALL - {S.HUMAN_REVIEW_REQUIRED}},
}

ACTOR_RANK = {"system": 0, "human": 1}


class TransitionError(ValueError):
    pass


def allowed(src: Status, dst: Status, actor: str = "system") -> bool:
    if src == dst:
        return True
    need = TRANSITIONS.get(src, {}).get(dst)
    return need is not None and ACTOR_RANK[actor] >= ACTOR_RANK[need]


def transition(a: Assessment, dst: Status, reason: str, actor: str = "system",
               at: str | None = None) -> None:
    """Record a status change.  ``at`` is the analysis timestamp (deterministic
    output); the wall clock is used only when no timestamp is supplied."""
    if a.status == dst:
        return
    if not allowed(a.status, dst, actor):
        raise TransitionError(f"{a.status.value} → {dst.value} not allowed for actor '{actor}'")
    if a.status == Status.HUMAN_REVIEW_REQUIRED and actor == "system" and a.review_triggers:
        raise TransitionError("review triggers still present; system cannot leave HUMAN_REVIEW_REQUIRED")
    a.history.append(Transition(from_status=a.status, to_status=dst, actor=actor, reason=reason,
                                at=at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()).to_dict())
    a.status = dst

"""Commit-time validation for reslab.

Reads .resdag/profile.json and enforces rules at three levels:
  off     — no check
  warn    — print warning, commit proceeds
  require — print error, commit fails (unless --no-validate)

Rules:
  hypothesis_parent — results must link to a hypothesis
  claim_structure   — claim text must contain template sections
  vocabulary        — domain tags must be in vocabulary

Applied in CLI layer only. The workflow Python API stays unconstrained.
``lab note`` is exempt from all validation (except in strict mode where
it is disabled entirely).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from resdag.claim import ClaimType

from reslab.profiles import Profile
from reslab.vocabulary import Vocabulary


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    rule: str       # hypothesis_parent, claim_structure, vocabulary
    level: str      # "warn" or "require"
    message: str
    suggestion: str  # actionable command to fix


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.level == "require" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.level == "warn" for i in self.issues)


# ---------------------------------------------------------------------------
# Section markers for template structure detection
# ---------------------------------------------------------------------------

_RESULT_SECTIONS = ("Question:", "Finding:", "Implication:")
_HYPOTHESIS_SECTIONS = ("Prediction:", "Rationale:", "If wrong:")
_METHOD_SECTIONS = ("Approach:", "Differs from prior work:", "Limitations:")


def _expected_sections(claim_type: ClaimType) -> tuple[str, ...]:
    """Return required section markers for a claim type, or empty tuple."""
    if claim_type is ClaimType.RESULT:
        return _RESULT_SECTIONS
    if claim_type is ClaimType.HYPOTHESIS:
        return _HYPOTHESIS_SECTIONS
    if claim_type is ClaimType.METHOD:
        return _METHOD_SECTIONS
    return ()


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------

def validate_commit(
    claim_type: ClaimType,
    claim_text: str,
    domains: Sequence[str],
    hypothesis_cid: str,
    profile: Profile,
    vocabulary: Vocabulary | None = None,
) -> ValidationResult:
    """Validate a claim against profile rules. Returns ValidationResult.

    Parameters
    ----------
    claim_type : ClaimType
        The type of claim being committed.
    claim_text : str
        The claim text.
    domains : Sequence[str]
        Domain tags on the claim.
    hypothesis_cid : str
        The hypothesis parent CID (empty string if none).
    profile : Profile
        The project profile with validation rules.
    vocabulary : Vocabulary | None
        The vocabulary for tag validation. Only needed when
        vocabulary rule is not "off".
    """
    result = ValidationResult()
    rules = profile.validation

    # --- hypothesis_parent ---
    if rules.hypothesis_parent != "off":
        # Only results need a hypothesis parent
        if claim_type is ClaimType.RESULT and not hypothesis_cid:
            result.issues.append(ValidationIssue(
                rule="hypothesis_parent",
                level=rules.hypothesis_parent,
                message="Result has no hypothesis parent.",
                suggestion='Run `lab hypothesize "your prediction"` first, then `lab execute --hypothesis <cid> "..."` to link them.',
            ))

    # --- claim_structure ---
    if rules.claim_structure != "off":
        sections = _expected_sections(claim_type)
        if sections:
            missing = [s for s in sections if s not in claim_text]
            if missing:
                result.issues.append(ValidationIssue(
                    rule="claim_structure",
                    level=rules.claim_structure,
                    message=f"Claim text is missing template sections: {', '.join(missing)}",
                    suggestion=f"Use the template in .resdag/templates/ — expected sections: {', '.join(sections)}",
                ))

    # --- vocabulary ---
    if rules.vocabulary != "off" and domains and vocabulary is not None:
        unknown = [
            d for d in domains
            if d not in vocabulary.tags
            and d not in vocabulary.aliases
            and d not in vocabulary.subtags
        ]
        if unknown:
            result.issues.append(ValidationIssue(
                rule="vocabulary",
                level=rules.vocabulary,
                message=f"Unknown domain tags: {', '.join(unknown)}",
                suggestion="Run `lab migrate-tags` to normalize, or add tags to .resdag/vocabulary.json.",
            ))

    return result

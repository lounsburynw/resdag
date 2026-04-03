"""Verification receipt structure.

A verification receipt is a Claim of type VERIFICATION that references
the verified claim as its parent. Structured metadata (method, result,
confidence) is encoded as JSON in the claim text field.

Verification receipts are DAG nodes with their own provenance — they can
be signed, have evidence attached, and be verified themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from resdag.claim import Claim, ClaimType
from resdag.dag import DAG


class VerificationResult(str, Enum):
    """Outcome of a verification attempt."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    PARTIAL = "partial"


@dataclass(frozen=True)
class VerificationReceipt:
    """Structured view of a verification receipt.

    Provides typed access to verification-specific fields that are
    encoded in the claim text of a VERIFICATION-type Claim.
    """

    target_cid: str
    result: VerificationResult
    method: str
    description: str = ""
    confidence: float | None = None


def create_receipt(
    target_cid: str,
    result: VerificationResult,
    method: str,
    description: str = "",
    confidence: float | None = None,
    evidence: tuple[str, ...] = (),
    domain: tuple[str, ...] = (),
    author: str = "",
    timestamp: str = "",
) -> Claim:
    """Create a verification receipt as a Claim.

    The receipt references the verified claim as its sole parent.
    Verification metadata is encoded as JSON in the claim text.
    """
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        raise ValueError(f"Confidence must be between 0.0 and 1.0, got {confidence}")

    payload: dict = {
        "description": description,
        "method": method,
        "result": result.value,
    }
    if confidence is not None:
        payload["confidence"] = confidence

    kwargs: dict = {
        "claim": json.dumps(payload, sort_keys=True),
        "type": ClaimType.VERIFICATION,
        "parents": (target_cid,),
        "evidence": evidence,
        "domain": domain,
        "author": author,
    }
    if timestamp:
        kwargs["timestamp"] = timestamp
    return Claim(**kwargs)


def parse_receipt(claim: Claim) -> VerificationReceipt:
    """Parse a verification Claim into a structured VerificationReceipt.

    Raises ValueError if the claim is not a valid verification receipt.
    """
    if claim.type != ClaimType.VERIFICATION:
        raise ValueError(f"Not a verification claim: type is {claim.type.value}")
    if not claim.parents:
        raise ValueError("Verification claim has no target (empty parents)")

    try:
        payload = json.loads(claim.claim)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid verification receipt payload: {e}") from e

    return VerificationReceipt(
        target_cid=claim.parents[0],
        result=VerificationResult(payload["result"]),
        method=payload["method"],
        description=payload.get("description", ""),
        confidence=payload.get("confidence"),
    )


def verification_status(cid: str, dag: DAG) -> list[VerificationReceipt]:
    """Find all verification receipts attached to a claim.

    Returns parsed receipts for all direct children of type VERIFICATION.
    """
    receipts = []
    for child_cid in dag.children(cid):
        child = dag.get(child_cid)
        if child.type == ClaimType.VERIFICATION:
            receipts.append(parse_receipt(child))
    return receipts

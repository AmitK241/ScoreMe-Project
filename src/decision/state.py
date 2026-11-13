"""The request lifecycle. Every status change goes through check_transition(), so illegal moves fail loudly."""

from .errors import InvalidTransition

RECEIVED = "RECEIVED"
PROCESSING = "PROCESSING"
RETRY_PENDING = "RETRY_PENDING"        # a dependency failed; the request can be retried
MANUAL_REVIEW = "MANUAL_REVIEW"        # a human must decide
APPROVED = "APPROVED"
REJECTED = "REJECTED"
INVALID = "INVALID"                    # failed input validation; never processed

ALLOWED = {
    RECEIVED: {PROCESSING},
    # PROCESSING -> PROCESSING is a progress checkpoint between stages.
    PROCESSING: {PROCESSING, RETRY_PENDING, MANUAL_REVIEW, APPROVED, REJECTED},
    RETRY_PENDING: {PROCESSING},
    MANUAL_REVIEW: {APPROVED, REJECTED},
    APPROVED: set(),
    REJECTED: set(),
    INVALID: set(),
}


def check_transition(current, target):
    if target not in ALLOWED.get(current, set()):
        raise InvalidTransition(f"cannot move a request from {current} to {target}")

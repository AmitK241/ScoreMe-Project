"""Exceptions used across the platform. The API maps each one to an HTTP status code."""


class DecisionError(Exception):
    status_code = 400


class ConfigError(DecisionError):
    """A workflow file is malformed. Raised at startup or on reload."""


class UnknownWorkflow(DecisionError):
    status_code = 404


class NotFound(DecisionError):
    status_code = 404


class IdempotencyConflict(DecisionError):
    """Same idempotency key was used with a different payload."""
    status_code = 409


class InvalidTransition(DecisionError):
    """A lifecycle move that the state machine does not allow."""
    status_code = 409


class InvalidReview(DecisionError):
    status_code = 422

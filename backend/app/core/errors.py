"""Domain exception hierarchy.

Owns: the set of failures callers may branch on.
Does not own: recovery logic. Raising a domain error is a statement about
what failed; deciding what to do next belongs to the caller.

Every module raises from this set rather than defining its own exception.
That gives two catch granularities that both matter in practice:
`except CamBrainError` for "shut this camera down cleanly", and
`except StreamError` for "this is a transport problem, retry".
"""

from __future__ import annotations

from app.core.logging import mask_url


class CamBrainError(Exception):
    """Base for every CamBrain domain error.

    Catching this means "something in this process failed in a way we
    anticipated". Anything not deriving from it is a bug.
    """


class StreamError(CamBrainError):
    """Frame acquisition failed: transport, decode, or source lifecycle.

    Sub-classing note: a transport failure is expected and recoverable — the
    pipeline reconnects. This is the single most frequently raised error in
    the codebase, which is why it has its own type rather than sharing one.
    """


class DetectionError(CamBrainError):
    """Detection output could not be interpreted.

    Raised when a model returns something structurally unexpected. Distinct
    from InferenceError because the model ran fine; the result was unusable.
    """


class InferenceError(CamBrainError):
    """Inference could not run: model missing, session creation failed, bad input."""


class RuleError(CamBrainError):
    """A rule could not be evaluated or is structurally invalid."""


class NotificationError(CamBrainError):
    """Alert delivery failed. Never fatal — the event is already persisted."""


class StorageError(CamBrainError):
    """Disk or database operation failed: quota exceeded, unwritable path, locked DB."""


class AuthError(CamBrainError):
    """Authentication or authorisation failed."""


class NotFoundError(CamBrainError):
    """A requested entity does not exist within the caller's tenant scope.

    Used for cross-tenant access too. See `docs/SECURITY.md` §4.3: a 403 would
    confirm the row exists, so tenancy violations surface as not-found.
    """


class ValidationError(CamBrainError):
    """Input failed domain validation, beyond what Pydantic already checked."""


def safe_error(message: str) -> str:
    """Scrub credentials from a message before it becomes an exception string.

    Call this whenever building an exception message from a URL or from text
    that might interpolate one. The logging layer redacts *emitted* events,
    but an exception message can be captured and re-raised elsewhere before
    it ever reaches a log.

    Args:
        message: Raw message.

    Returns:
        The message with URL credentials and inline secrets masked.
    """
    return mask_url(message)

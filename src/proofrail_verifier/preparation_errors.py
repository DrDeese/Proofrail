"""Controlled error categories for offline case preparation."""


class InvalidPreparationInput(ValueError):
    """Raised for invalid repositories, refs, claims, or source structure."""


class PreparationFailure(RuntimeError):
    """Raised when deterministic evidence generation cannot complete."""


class OutputWriteFailure(OSError):
    """Raised when the atomic output directory cannot be written."""

class ValidationError(ValueError):
    """Safe, actionable input validation failure."""


class ResourceLimit(ValidationError):
    """A documented local processing bound was reached; no partial success."""

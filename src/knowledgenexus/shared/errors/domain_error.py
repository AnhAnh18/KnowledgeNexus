class DomainError(Exception):
    """Base domain exception."""


class NotFoundError(DomainError):
    """Entity not found."""


class ValidationError(DomainError):
    """Domain validation failed."""


class StorageError(DomainError):
    """Storage operation failed."""

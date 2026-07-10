class ContractLoadError(RuntimeError):
    """Raised when contract schemas cannot be loaded from disk."""


class ContractSchemaNotFoundError(KeyError):
    """Raised when a requested contract schema name is not loaded."""

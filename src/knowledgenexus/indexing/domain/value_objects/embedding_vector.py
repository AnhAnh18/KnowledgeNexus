from dataclasses import dataclass, field


@dataclass(frozen=True)
class SparseVector:
    """Sparse vector (token_id → weight) from BGE-M3 lexical output."""
    indices: list[int]
    values: list[float]

    def __post_init__(self) -> None:
        if len(self.indices) != len(self.values):
            raise ValueError(
                f"Sparse vector indices ({len(self.indices)}) "
                f"and values ({len(self.values)}) length mismatch"
            )

    def to_qdrant(self) -> dict[str, list]:
        """Convert to Qdrant sparse vector format."""
        return {
            "indices": list(self.indices),
            "values": list(self.values),
        }


@dataclass(frozen=True)
class EmbeddingVector:
    values: list[float]
    model_name: str
    dimension: int
    sparse: SparseVector | None = None

    def __post_init__(self) -> None:
        if len(self.values) != self.dimension:
            raise ValueError(
                f"Vector length {len(self.values)} does not match dimension {self.dimension}"
            )

from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingVector:
    values: list[float]
    model_name: str
    dimension: int

    def __post_init__(self) -> None:
        if len(self.values) != self.dimension:
            raise ValueError(
                f"Vector length {len(self.values)} does not match dimension {self.dimension}"
            )

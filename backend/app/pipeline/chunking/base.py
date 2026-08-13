from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    index: int
    text: str
    token_count: int


class Chunker(ABC):
    @abstractmethod
    def chunk(self, text: str) -> list[TextChunk]: ...

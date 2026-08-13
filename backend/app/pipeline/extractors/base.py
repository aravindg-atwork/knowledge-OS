from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedDoc:
    text: str
    extracted_title: str | None = None
    author: str | None = None


class ContentExtractor(ABC):
    @abstractmethod
    def extract(self, content: bytes) -> ExtractedDoc:
        """Parse raw bytes into plain text (+ any metadata the format carries)."""


class UnsupportedMimeTypeError(ValueError):
    pass

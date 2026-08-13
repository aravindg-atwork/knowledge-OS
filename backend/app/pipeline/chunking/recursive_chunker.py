from app.pipeline.chunking.base import Chunker, TextChunk


class RecursiveChunker(Chunker):
    """Paragraph-aware sliding window. Token counts are approximated by word
    count (a fixed heuristic, not a real tokenizer) -- fine for budgeting
    chunk size, not meant to match model-specific tokenization exactly.
    """

    def __init__(self, max_tokens: int = 500, overlap_tokens: int = 50) -> None:
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens

    def chunk(self, text: str) -> list[TextChunk]:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            return []

        # Break any paragraph larger than the budget into fixed word windows
        # so a single oversized paragraph can't blow past max_tokens.
        units: list[list[str]] = []
        for paragraph in paragraphs:
            words = paragraph.split()
            if len(words) <= self._max_tokens:
                units.append(words)
            else:
                for i in range(0, len(words), self._max_tokens):
                    units.append(words[i : i + self._max_tokens])

        chunks: list[TextChunk] = []
        current: list[str] = []
        for unit in units:
            if current and len(current) + len(unit) > self._max_tokens:
                chunks.append(self._finalize(len(chunks), current))
                overlap = current[-self._overlap_tokens :] if self._overlap_tokens else []
                current = overlap + unit
            else:
                current.extend(unit)

        if current:
            chunks.append(self._finalize(len(chunks), current))

        return chunks

    def _finalize(self, index: int, words: list[str]) -> TextChunk:
        return TextChunk(index=index, text=" ".join(words), token_count=len(words))

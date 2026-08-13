from app.pipeline.chunking.recursive_chunker import RecursiveChunker


def test_empty_text_produces_no_chunks():
    chunker = RecursiveChunker(max_tokens=50, overlap_tokens=5)
    assert chunker.chunk("") == []
    assert chunker.chunk("   \n\n   ") == []


def test_single_word_text_produces_one_chunk():
    chunker = RecursiveChunker(max_tokens=50, overlap_tokens=5)
    chunks = chunker.chunk("Hello")
    assert len(chunks) == 1
    assert chunks[0].text == "Hello"
    assert chunks[0].token_count == 1
    assert chunks[0].index == 0


def test_short_text_fits_in_a_single_chunk():
    chunker = RecursiveChunker(max_tokens=100, overlap_tokens=10)
    text = "First paragraph here.\n\nSecond paragraph here."
    chunks = chunker.chunk(text)
    assert len(chunks) == 1
    assert "First paragraph" in chunks[0].text
    assert "Second paragraph" in chunks[0].text


def test_long_text_splits_into_multiple_chunks_with_overlap():
    paragraphs = [f"paragraph{i} " + " ".join(["word"] * 20) for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunker = RecursiveChunker(max_tokens=50, overlap_tokens=10)

    chunks = chunker.chunk(text)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= 50
    # overlap: the tail words of one chunk should reappear at the start of the next
    first_chunk_tail = chunks[0].text.split()[-10:]
    second_chunk_head = chunks[1].text.split()[:10]
    assert first_chunk_tail == second_chunk_head


def test_oversized_single_paragraph_is_split_on_its_own():
    text = " ".join(["word"] * 250)
    chunker = RecursiveChunker(max_tokens=100, overlap_tokens=0)

    chunks = chunker.chunk(text)

    assert len(chunks) == 3
    assert chunks[0].token_count == 100
    assert chunks[1].token_count == 100
    assert chunks[2].token_count == 50


def test_chunk_indices_are_sequential():
    text = "\n\n".join(f"paragraph number {i}" for i in range(5))
    chunker = RecursiveChunker(max_tokens=5, overlap_tokens=0)
    chunks = chunker.chunk(text)
    assert [c.index for c in chunks] == list(range(len(chunks)))

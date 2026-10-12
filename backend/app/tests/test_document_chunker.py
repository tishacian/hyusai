from app.services.rag.ingest.parser.chunker import ChunkingMethod, DocumentChunker


SENTENCES = [f"Sentence number {i} talks about topic {i % 3}." for i in range(30)]
TEXT = " ".join(SENTENCES)


def test_sentence_packs_whole_sentences_up_to_chunk_size():
    chunks = DocumentChunker().chunk(TEXT, method="sentence", chunk_size=200, overlap=0)
    assert 1 < len(chunks) < len(SENTENCES)
    assert all(len(c) <= 200 for c in chunks)
    assert all(c.endswith(".") for c in chunks)
    assert " ".join(chunks) == TEXT


def test_sentence_overlap_repeats_trailing_sentences():
    chunks = DocumentChunker().chunk(TEXT, method=ChunkingMethod.SENTENCE, chunk_size=200, overlap=60)
    assert all(len(c) <= 200 for c in chunks)
    for previous, current in zip(chunks, chunks[1:]):
        first = current.split(". ")[0] + "."
        assert previous.endswith(first)


def test_sentence_splits_an_oversized_sentence():
    chunks = DocumentChunker().sentence_chunking("x" * 450 + ".", chunk_size=200, overlap=0)
    assert [len(c) for c in chunks] == [200, 200, 51]


def test_markdown_splits_by_headers_and_prefixes_heading_path():
    text = (
        "Intro line.\n\n# Guide\nTop body.\n\n## Install\nRun it.\n\n"
        "```\n# not a header\n```\n\n## Usage\nUse it.\n\n# Annex\nMore."
    )
    chunks = DocumentChunker().chunk(text, method="markdown", chunk_size=500)
    assert chunks[0] == "Intro line."
    assert chunks[1] == "Guide\n\nTop body."
    assert chunks[2].startswith("Guide > Install\n\nRun it.")
    assert "# not a header" in chunks[2]
    assert chunks[3] == "Guide > Usage\n\nUse it."
    assert chunks[4] == "Annex\n\nMore."


def test_markdown_splits_long_sections_within_chunk_size():
    text = "# Title\n" + TEXT
    chunks = DocumentChunker().markdown_chunking(text, chunk_size=200, overlap=0)
    assert len(chunks) > 1
    assert all(c.startswith("Title\n\n") and len(c) <= 200 for c in chunks)


def test_semantic_groups_related_sentences():
    cats = [f"The cat number {i} purrs and sleeps on the sofa." for i in range(6)]
    rockets = [f"The rocket stage {i} burns liquid fuel in orbit." for i in range(6)]
    interleaved = [s for pair in zip(cats, rockets) for s in pair]
    chunks = DocumentChunker().chunk(" ".join(interleaved), method="semantic", chunk_size=2000)
    assert sorted(" ".join(chunks).split(". ")) == sorted(" ".join(interleaved).split(". "))
    assert any(all("cat" in s for s in c.split(". ")) for c in chunks)
    assert all(not ("cat" in c and "rocket" in c) for c in chunks)


def test_semantic_falls_back_on_short_text():
    assert DocumentChunker().chunk("One. Two.", method="semantic", chunk_size=100) == ["One. Two."]


def test_unknown_method_string_falls_back_to_recursive():
    assert DocumentChunker().chunk("short text", method="nope", chunk_size=100) == ["short text"]


def test_empty_text_yields_no_chunks():
    chunker = DocumentChunker()
    for method in ("sentence", "markdown", "semantic"):
        assert chunker.chunk("   ", method=method) == []

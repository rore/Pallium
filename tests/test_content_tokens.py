from semantic.content_tokens import content_tokens, has_content_overlap


def test_extracts_content_words():
    tokens = content_tokens("how is the weather today")
    assert "weather" in tokens
    assert "today" in tokens
    assert "how" not in tokens  # stopword
    assert "is" not in tokens   # stopword
    assert "the" not in tokens  # stopword


def test_no_overlap_weather_vs_catalog():
    assert has_content_overlap(
        "how is the weather today",
        "Arrival-time ordering is now the default for all branch reservation queues"
    ) is False


def test_overlap_reservation_query():
    assert has_content_overlap(
        "what did we decide about reservation ordering",
        "Decision: use arrival-time ordering for reservation queues"
    ) is True


def test_prefix_match_batch_batches():
    # "batches" in query should match "batch" in candidate via prefix matching
    assert has_content_overlap(
        "can you remind me what we had latest about batches",
        "The inventory batch digest is preserved with an explicit no-login constraint."
    ) is True


def test_empty_texts():
    assert has_content_overlap("", "some text") is False
    assert has_content_overlap("some text", "") is False

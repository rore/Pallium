---
id: add-multilingual-tokenization-and-embedding-support
title: Multilingual tokenization and embedding support
status: done
priority: high
commitment: committed
milestone: Done
---

## Summary

Make Pallium's tokenization, lexical retrieval, and embedding pipeline
language-agnostic so content in any script is handled natively without
language detection or switching.

## Why

Pallium's original tokenization was ASCII/Latin-only. Non-Latin content
(Hebrew, Arabic, CJK, Cyrillic) produced no usable tokens, breaking lexical
retrieval and content-overlap gates for multilingual containers.

## In Scope

- Unicode-aware tokenization centralized in `core/text.py`
- Hebrew, Arabic, CJK, Cyrillic script support
- CJK character-per-token tokenization (no word segmentation dependency)
- Combining mark stripping (Hebrew niqud, Arabic vowels, Latin diacritics)
- Cross-script content-overlap bypass (defer to vector similarity when query
  and candidate use entirely different scripts)
- `EmbedMode` for query/passage prefix support on multilingual embedding
  models
- Auto-detection of query/passage prefixes for known model families (E5)
- Multilingual stopword sets (English + Hebrew) supplementing IDF weighting
- Default embedding model changed to `intfloat/multilingual-e5-small`

## Out of Scope

- Word segmentation for CJK (character tokenization is sufficient for current
  retrieval quality)
- Language detection or per-language routing
- Transliteration or cross-language query expansion

## Done When

1. Tokenization produces real tokens for Hebrew, Arabic, CJK, and Cyrillic
   content.
2. Lexical retrieval works across scripts with combining mark normalization.
3. Cross-script containers don't false-block on content-overlap gates.
4. Embedding provider supports prefix modes for multilingual models.
5. Test coverage spans multilingual scenarios across all affected layers.

## Notes

Shipped. Test coverage includes Hebrew, Chinese, and mixed-language scenarios.

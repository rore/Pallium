# Multilingual Support — Design Spec

**Date:** 2026-04-05
**Status:** Draft

---

## Problem

Pallium is English-only. The embedding model (`bge-small-en-v1.5`), the lexical tokenizer (`[a-z0-9]+`), stopword lists, and several heuristic patterns all assume English/ASCII text. For non-Latin scripts (Hebrew, Arabic, CJK, Cyrillic), lexical retrieval returns zero results, the content-overlap injection gate is silently bypassed, and non-English queries route to the `low_value` dead-end.

## Goals

1. Make retrieval work for non-English content — both vector and lexical.
2. Make the routing pipeline produce correct decisions for non-English queries.
3. Do not regress English behavior.
4. Keep the change minimal — fix tokenization and embedding; defer FTS5, language detection, and translation.

## Non-Goals

- FTS5 migration (separate Step 2, own spec)
- Language detection metadata on items
- Translated aliases or cross-language translation
- Non-English LLM prompt variants
- CJK proper word segmentation (character-level is acceptable for Phase 1)
- Per-language morphological stemming

---

## Implementation Sequence

This spec is one change, not two PRs. However, the tokenizer changes (1.1-1.4) and the embedding model swap (1.5-1.6) have different risk profiles. Implement in this order and run full regression between phases:

1. **Phase A — Tokenizer + routing fixes** (1.1-1.4, content-overlap bypass, behavioral mitigations)
   - Run full test suite (854 tests) + English eval suite
   - Verify no English regression before proceeding
2. **Phase B — Embedding model swap** (1.5-1.6)
   - Reprocess data (`clean-data.sh`)
   - Re-validate similarity threshold
   - Run full test suite + English eval suite + new multilingual evals

If Phase A introduces regressions, fix them before Phase B. This keeps attribution clear without the overhead of separate PRs.

**Both phases require a full data reprocess.** Phase A changes what `normalize_for_index()` produces — existing lexical index entries contain ASCII-only normalized text and must be rebuilt. Phase B changes the embedding model — existing vector index entries must be rebuilt. In practice, a single `clean-data.sh` after both phases is sufficient, but if verifying Phase A in isolation, reprocess between phases too.

---

## Step 1 — Multilingual Unblock

### 1.1 Extract tokenizer to `core/text.py` and replace TOKEN_PATTERN

**Current state:** `TOKEN_PATTERN = re.compile(r"[a-z0-9]+")` is duplicated in 4 files:
- `semantic/common.py:17`
- `retrieval/lexical.py:18`
- `storage/sqlite_search.py:19`
- `core/service.py:32`

Four copies of a complex Unicode-aware regex is a maintenance hazard. All four consumers already depend on `core/` — storage imports from `core.filters`, `core.models`, `core.visibility`; retrieval imports from `core.models`; semantic imports from `core.models`.

**Change:** Create `core/text.py` with the canonical tokenizer. All four files import from it. No layer boundary violation.

**Target tokenizer:**

```python
# core/text.py
import re
import unicodedata

# CJK ideographs: each character = one token (no inter-word spaces in CJK)
_CJK_RANGES = (
    "\u3040-\u309F"   # Hiragana
    "\u30A0-\u30FF"   # Katakana
    "\u3400-\u4DBF"   # CJK Extension A
    "\u4E00-\u9FFF"   # CJK Unified Ideographs
    "\uF900-\uFAFF"   # CJK Compatibility Ideographs
)
_CJK_CHAR = f"[{_CJK_RANGES}]"
_NON_CJK_WORD = f"[^\\W_{_CJK_RANGES}]+"

TOKEN_PATTERN = re.compile(f"{_CJK_CHAR}|{_NON_CJK_WORD}", re.UNICODE)


def strip_combining_marks(text: str) -> str:
    """Strip combining marks (Hebrew niqud, Arabic vowels, Latin diacritics).

    Uses NFKD normalization + combining character removal.
    "decísion" -> "decision", "סִפְרִיָּה" -> "ספריה", "مَرْحَبًا" -> "مرحبا".
    """
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_for_index(text: str) -> str:
    """Normalize text for lexical indexing and text comparison."""
    return " ".join(TOKEN_PATTERN.findall(strip_combining_marks(text).lower()))


def tokenize_text(text: str) -> list[str]:
    """Tokenize text into a list of normalized tokens."""
    return TOKEN_PATTERN.findall(strip_combining_marks(text).lower())
```

Behavior:
- Latin: `"hello world"` -> `["hello", "world"]`
- Digits: `"Python3"` -> `["python3"]`
- Hyphen: `"bge-small-en"` -> `["bge", "small", "en"]`
- Underscore: `"hello_world"` -> `["hello", "world"]`
- Hebrew: `"שלום עולם"` -> `["שלום", "עולם"]`
- Hebrew + niqud: `"סִפְרִיָּה"` -> `["ספריה"]` (combining marks stripped, one correct token)
- Arabic: `"مرحبا بالعالم"` -> `["مرحبا", "بالعالم"]`
- Arabic + vowels: `"مَرْحَبًا"` -> `["مرحبا"]` (combining marks stripped)
- Cyrillic: `"Привет мир"` -> `["привет", "мир"]`
- CJK: `"今天天气很好"` -> `["今", "天", "天", "气", "很", "好"]` (character-level)
- Korean: `"안녕하세요 세계"` -> `["안녕하세요", "세계"]` (word-level, spaces preserved)
- Mixed: `"Tokyo東京 station"` -> `["tokyo", "東", "京", "station"]`

No external dependencies — stdlib `re` with Unicode mode.

**Migration:** Remove the local `TOKEN_PATTERN`, `strip_diacritics` / `_strip_diacritics`, and `_normalize_for_index` definitions from all four files. Import from `core/text.py`. The duplicate `strip_diacritics` comments ("both copies must stay in sync") become obsolete.

### 1.2 Keep English plural stemmer, guard it

**Current state:** `_token_variants()` in `retrieval/lexical.py:43-51` and inline in `content_tokens()` in `semantic/common.py:134-139`. Query-side only (never applied at index time).

**Change:** Keep the stemmer but add a guard — only apply to ASCII-only tokens:

```python
def _token_variants(token: str) -> tuple[str, ...]:
    variants = [token]
    if not token.isascii():
        return tuple(variants)
    # existing English plural rules unchanged...
```

Apply the same guard to the inline copy in `content_tokens()`.

This prevents the English suffix rules from producing garbage on non-Latin tokens. The rules already don't fire for non-Latin (no Hebrew word ends in "-ies"), but the explicit guard is clearer and future-safe.

### 1.3 Expand stopword sets

**CONTENT_STOPWORDS** (`semantic/common.py:105-120`): Add Hebrew function words to the existing set. Union approach — English + Hebrew together. No collision risk (different scripts).

**CONSOLIDATION_STOPWORDS** (`capabilities/consolidation.py:20-45`): Same approach.

Hebrew stopwords (initial set):
```python
HEBREW_STOPWORDS: frozenset[str] = frozenset({
    "של", "על", "את", "עם", "אל", "מן", "לא", "כי", "גם", "או",
    "אם", "הוא", "היא", "הם", "הן", "אני", "אנחנו", "אתה",
    "זה", "זו", "זאת", "אלה", "כל", "עוד", "רק", "כבר", "מאוד",
    "בין", "אבל", "אז", "כמו", "יותר", "פה", "שם",
})
```

Then: `CONTENT_STOPWORDS = ENGLISH_STOPWORDS | HEBREW_STOPWORDS`

Add other languages incrementally as needed. The IDF layer handles bulk frequency suppression; explicit stopwords cover the gaps IDF misses.

**Consolidation tokenizer alignment:** `capabilities/consolidation.py:482-489` has its own `_tokenize()` using `character.isalnum()`. This is already Unicode-aware but uses a different tokenization strategy than `TOKEN_PATTERN`. It should import `tokenize_text` from `core/text.py` for consistency, so consolidation grouping uses the same token boundaries as lexical retrieval.

### 1.4 Cross-language content-overlap bypass

**The problem:** The content-overlap injection gate in `_candidate_has_content_overlap()` checks whether query tokens intersect with candidate tokens. After the tokenizer fix, a Hebrew query produces Hebrew tokens and an English memory produces English tokens — zero intersection. The gate blocks injection.

This is not a future edge case. In the current product shape (agent conversation memory), a Hebrew-speaking user's container routinely has both Hebrew user messages and English agent responses, tool call summaries, and technical content. A Hebrew query must be able to retrieve English-language memories from the same container.

**Change:** Add a script-aware bypass to `_candidate_has_content_overlap()`:

```python
def _scripts_differ(tokens_a: set[str], tokens_b: set[str]) -> bool:
    """True when two token sets use entirely different Unicode scripts.

    When scripts differ, content-overlap is not meaningful — defer to
    vector similarity as the relevance signal.
    """
    if tokens_a & tokens_b:
        return False  # shared tokens → same script, overlap meaningful
    def _is_latin(t: str) -> bool:
        return t[0].isascii() and t[0].isalpha()
    has_latin_a = any(_is_latin(t) for t in tokens_a)
    has_latin_b = any(_is_latin(t) for t in tokens_b)
    has_nonlatin_a = any(not _is_latin(t) for t in tokens_a if t[0].isalpha())
    has_nonlatin_b = any(not _is_latin(t) for t in tokens_b if t[0].isalpha())
    # Scripts differ if one side is only Latin and the other is only non-Latin
    return (has_latin_a and not has_nonlatin_a and has_nonlatin_b and not has_latin_b) or \
           (has_nonlatin_a and not has_latin_a and has_latin_b and not has_nonlatin_b)
```

When scripts differ, the gate returns True (pass) — deferring to vector similarity as the relevance signal. When scripts overlap (same-language query and candidate), the gate applies normally.

### 1.5 Swap embedding model

**Model:** `intfloat/multilingual-e5-small` — 384 dims, 100+ languages, same dimension as current bge-small-en.

**fastembed incompatibility:** `multilingual-e5-small` is not in fastembed's supported model list. The ONNX provider is the required path. The fastembed provider should log a clear error if configured with an unsupported model. This is not a blocker — the ONNX provider is already the recommended path.

**Config change:** `pallium.local.toml`:
```toml
[embedding_providers.onnx]
kind = "onnx"
model = "intfloat/multilingual-e5-small"
query_prefix = "query: "
passage_prefix = "passage: "
```

**Provider change — query/passage prefix:**

The `EmbeddingProvider` ABC needs to distinguish query-time vs document-time embedding.

Add `query_prefix` and `passage_prefix` to `EmbeddingProviderConfig`. The provider reads them from config and prepends the correct prefix based on the call mode.

```python
from typing import Literal

EmbedMode = Literal["query", "passage"]

class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str], *, mode: EmbedMode = "passage") -> list[list[float]]:
        ...
```

Call sites:
- `retrieval/vector.py:72` — passes `mode="query"`
- `core/vector_embed.py:58,121,176` — passes `mode="passage"` (default)

For models that don't use prefixes (like the current bge-small-en), the prefix config fields are absent/empty and `embed()` ignores the mode parameter. Backward compatible.

**Default fallback:** The hardcoded `"BAAI/bge-small-en-v1.5"` fallback in `app/config.py:131` stays unchanged. Do not silently switch the default model for existing deployments. Instead, log a warning when the fallback fires: "Using default English-only embedding model (BAAI/bge-small-en-v1.5). Configure [embedding_providers] in pallium.local.toml for multilingual support."

**Min similarity threshold:** 0.55 was validated for bge-small-en. Must be re-validated for multilingual-e5-small with correct prefixes. The threshold is configurable via `vector_index.min_similarity` in TOML. Start with 0.55, run evals, adjust.

**Startup safety:** The existing model mismatch check in `app/dependencies.py:245-255` will catch the model change and disable vector retrieval until reindex. This is the intended behavior.

**English labels in `build_embedding_text()`:** The English labels ("Decision: ", "Task: ", "Interest: ", etc.) prepended to embedding text stay for now. They serve as semantic type markers that help the embedding model understand the role of the content. With `multilingual-e5-small`, `"passage: Decision: שבחרנו ב-PostgreSQL"` is valid mixed-language input that the model handles. Revisit only if evals show that labels hurt cross-language similarity — they are more likely to help than hurt.

### 1.6 Reindex

After both phases, delete all runtime data and restart:
```bash
bash scripts/clean-data.sh
```

Startup creates fresh DB + empty vector index. The background processor re-ingests and `VectorEmbedder.reconcile()` backfills vector entries.

---

## Behavioral Changes to Verify

These are real behavior changes, not bugs. They need eval coverage:

### B1: Non-Latin queries no longer route to `low_value`

**Current:** `routing_signals.py:388` — `normalize_for_index(text)` on Hebrew returns `""` -> `low_value`.
**After:** Hebrew tokens survive -> normal routing.
**Risk:** Low. This is the desired behavior.

### B2: Content-overlap injection gate activates for non-Latin

**Current:** Non-Latin queries produce empty `content_tokens()` -> `len(query_ct) > 2` is False -> gate bypassed.
**After:** Non-Latin queries produce real tokens -> gate activates.
**Risk:** Mitigated by the script-aware bypass (1.4). Same-language queries get the correct gate behavior. Cross-language queries bypass the gate and defer to vector similarity.

### B3: `_looks_like_low_value_meta_update` false negatives

**Current:** English phrases ("task complete", "nothing new to report") are detected and suppressed.
**After:** Non-English equivalents are not detected.
**Risk:** Low. These are assistant-generated meta-updates; agents typically generate them in the prompt language (English). No action needed for Phase 1.

### B4: Summary echo suppression may over-trigger for non-English

**Current:** `routing_suppression.py:91-92` uses `normalize_for_index().split()` without stopword removal. Non-English function words are not filtered, inflating overlap scores.
**Risk:** Low for Phase 1. The Hebrew stopwords added to `CONTENT_STOPWORDS` don't help here (this call site doesn't use `content_tokens()`). Monitor for false positives in echo suppression for non-English content.

### B5: English noise-token lists in anchor/constraint display values

**Current:** `anchors.py` and `constraints.py` strip English leading/trailing noise tokens ("a", "the", "for", etc.).
**After:** Non-English noise tokens are not stripped.
**Risk:** Cosmetic only. No functional impact.

### B6: `_is_substantive_summary` passes non-English content

**Current:** `common.py:540` uses `TOKEN_PATTERN.findall(source_item.content.lower())` with threshold `len(content_tokens) >= 4`. Non-English-only source items produce zero tokens -> classified as non-substantive.
**After:** Non-English content produces real tokens -> classified as substantive when >= 4 tokens.
**Risk:** Low. This is the correct behavior — non-English content IS substantive. Previously it was silently discarded.

### CJK IDF score distribution

CJK character-level tokenization means each ideograph is a token. Common characters will get low IDF (correct), but the granularity is finer than word-level — a 6-character Chinese query produces 6 tokens where an English query of similar semantic weight produces 2-3. The IDF sum for CJK queries will tend to be higher. This is acceptable for Phase 1 because:
- CJK lexical scores are relative to other CJK documents in the same corpus
- RRF fusion normalizes by rank, not by raw score
- The IDF scale factor (`_IDF_SCORE_SCALE = 1`) may need per-script calibration if mixed-script corpora show score imbalance, but this is a tuning concern, not a correctness concern

---

## Files Changed

| File | Change |
|---|---|
| **`core/text.py`** | **New file.** Canonical `TOKEN_PATTERN`, `strip_combining_marks`, `normalize_for_index`, `tokenize_text` |
| `semantic/common.py` | Remove local `TOKEN_PATTERN`, `strip_diacritics`, `normalize_for_index`. Import from `core/text`. Expand `CONTENT_STOPWORDS` with Hebrew. Guard `_token_variants` in `content_tokens()` with `isascii()`. |
| `retrieval/lexical.py` | Remove local `TOKEN_PATTERN`, `_strip_diacritics`. Import from `core/text`. Guard `_token_variants` with `isascii()`. |
| `storage/sqlite_search.py` | Remove local `TOKEN_PATTERN`, `_strip_diacritics`. Import from `core/text`. |
| `core/service.py` | Remove local `TOKEN_PATTERN`, `_strip_diacritics`, `_normalize_for_index`. Import from `core/text`. |
| `capabilities/consolidation.py` | Expand `CONSOLIDATION_STOPWORDS` with Hebrew. Import `tokenize_text` from `core/text` to replace local `_tokenize()`. |
| `providers/embedding/base.py` | Add `EmbedMode = Literal["query", "passage"]`, add `mode` parameter to `embed()` |
| `providers/embedding/onnx_provider.py` | Accept `query_prefix`/`passage_prefix` in constructor, prepend in `embed()` based on `mode` |
| `providers/embedding/fastembed_provider.py` | Pass through `mode` parameter. Log error if model not in fastembed's supported list. |
| `app/config.py` | Add `query_prefix`/`passage_prefix` to `EmbeddingProviderConfig`. Add warning log when English-only fallback fires. |
| `retrieval/vector.py` | Pass `mode="query"` to `embed()` |
| `core/vector_embed.py` | Pass `mode="passage"` to `embed()` (explicit) |
| `semantic/agent_conversation_memory_routing_selection.py` | Add `_scripts_differ` bypass to `_candidate_has_content_overlap()` |
| `pallium.local.toml` | Update model name, add `query_prefix`/`passage_prefix` |
| `pallium.example.toml` | Same |
| `tests/test_lexical_tokenize.py` | Update token expectations, add Hebrew/CJK/niqud/mixed-script test cases |

---

## Step 2 — FTS5 Migration (Separate Spec)

Deferred to a separate design spec. Key items for that spec:

1. FTS5 virtual table with `unicode61` tokenizer, parallel to `index_entries`
2. Pre-process text before FTS5 insertion: strip combining marks + insert spaces between CJK characters (align with Phase 1 Python tokenizer)
3. Replace `search_index_entries()` Python full-scan with `MATCH` + `bm25()` queries
4. Reconstruct `matched_tokens` for routing (FTS5 doesn't return them natively)
5. Move visibility filtering to SQL or post-filter
6. Align `normalize_for_index()` in `core/text.py` with `unicode61` behavior
7. Consider `trigram` tokenizer as secondary layer for fuzzy matching
8. Also closes the "lexical retrieval scaling" roadmap item

---

## Eval Plan

### New eval scenarios needed

1. **Same-language retrieval:** Hebrew query -> Hebrew memory (lexical + vector)
2. **Cross-language retrieval:** Hebrew query -> English memory (vector, content-overlap bypass)
3. **Mixed-language thread:** Thread with Hebrew and English messages -> correct extraction and retrieval
4. **CJK character-level:** Chinese query -> Chinese memory via character token overlap
5. **Exact-name recall:** Technical terms, product names, identifiers across languages
6. **Injection gate correctness:** Verify content-overlap gate passes same-language, bypasses cross-language
7. **Routing correctness:** Non-Latin queries don't route to `low_value`
8. **English non-regression:** Full existing eval suite passes unchanged

### Threshold re-validation

- Run vector retrieval eval with multilingual-e5-small at threshold 0.55
- Measure false positive / false negative rates
- Adjust threshold if needed (configurable, no code change)

---

## Documentation Updates

These must land with the implementation, not as follow-ups:

| File | Update |
|---|---|
| `docs/context/state.md` | Update model reference from bge-small-en to multilingual-e5-small. Update "language-agnostic — no stopword lists" to reflect expanded stopword approach. |
| `docs/context/decisions.md` | New entry: multilingual tokenizer and embedding model choice. New entry: cross-language content-overlap bypass rationale. |
| `docs/context/architecture.md` | Note multilingual retrieval capability in the hybrid retrieval section. |
| `roadmap/board.md` | Add multilingual support item (this is a new capability, not a bug fix). |

---

## Risk Summary

| Risk | Severity | Mitigation |
|---|---|---|
| Content-overlap gate blocks cross-language results | High | Script-aware bypass in `_candidate_has_content_overlap()` |
| e5 prefix not applied -> poor similarity scores | High | Provider interface with `Literal["query", "passage"]` mode + config-driven prefix |
| Min similarity threshold wrong for new model | Medium | Re-validate with evals; threshold is configurable |
| `canonical_key` format changes for existing records | Low | Old records stay ASCII-normalized; new records get Unicode tokens. Full reprocess resolves it. |
| Hebrew stopwords incomplete | Low | Start with common set, expand based on eval results |
| CJK IDF score distribution skew | Low | RRF normalizes by rank; tuning concern, not correctness |

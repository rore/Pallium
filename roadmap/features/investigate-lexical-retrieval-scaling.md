---
id: investigate-lexical-retrieval-scaling
title: Investigate lexical retrieval scaling beyond full-scan
status: done
priority: high
commitment: committed
milestone: Next
---

## Summary

The lexical search implementation loads ALL index entries into memory on every query, tokenizes them in Python, and scores by token overlap. This works for development (hundreds of entries) but will not scale to production workloads.

## Current Architecture

`storage/sqlite_search.py:search_index_entries()` does:

1. `SELECT * FROM index_entries WHERE index_type = 'lexical'` — loads entire lexical index into memory
2. For each record: tokenize text_view, compute token overlap with query, score
3. Filter by container_ref, thread_ref, visibility — all in Python after loading

Every query pays the cost of loading and tokenizing the full corpus, regardless of how much is relevant.

## Why This Matters

- A single container query loads entries from ALL containers
- As the database grows (thousands of entries across many containers), every query slows linearly
- Memory usage grows linearly with corpus size per query
- The Python tokenization loop is CPU-bound — no database optimization possible

## Near-Term Mitigation: Container-Scoped Pre-Filtering

Queries are always scoped to a `container_ref`. Moving the container filter into the SQL WHERE clause (instead of post-load Python filtering) would dramatically reduce the scan set. This is the smallest change with the biggest impact:

- Join index_entries → source_items/memory_objects to filter by container_ref in SQL
- Or denormalize container_ref onto index_entries for a simple WHERE clause
- Reduces scan from "entire database" to "one container's entries"

## Medium-Term: SQL-Native Full-Text Search

### SQLite FTS5
- Virtual table with built-in BM25 ranking
- Tokenization, indexing, and scoring all in C — no Python loop
- Handles IDF natively
- Requires: FTS5 table, triggers to sync with index_entries, migration for existing data
- Tradeoff: more complex schema, FTS5 tokenizer may differ from current TOKEN_PATTERN

### PostgreSQL Full-Text Search
- When Pallium adds PostgreSQL support, `tsvector`/`tsquery` with `ts_rank` handles this natively
- Language-aware stemming and stopword filtering built in
- GIN indexes for fast lookup
- The current Python scoring code would be replaced entirely by SQL-native search

## Long-Term: External Search Engine

For very large deployments:
- Elasticsearch, Meilisearch, or Typesense
- Handles scaling, ranking, faceting out of the box
- Adds operational complexity (separate service)

## Investigation Deliverables

1. Benchmark current query latency at 100, 1K, 10K, 100K index entries
2. Prototype container_ref pre-filtering — measure improvement
3. Evaluate FTS5 migration path: schema changes, trigger complexity, BM25 quality vs current scoring
4. Document decision: pre-filter vs FTS5 vs defer to PostgreSQL migration

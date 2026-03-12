# Public Corpus Eval Assets

This directory stores reviewed metadata for the public real-interaction eval layer.

What is committed:
- `wildchat_review_manifest.json`: reviewed episode selections and labels for the primary WildChat-backed realism slice
- `wildbench_review_manifest.json`: reviewed episode selections and labels for the complementary WildBench-backed task slice
- `wildbench_developer_continuation_manifest.json`: small reviewed WildBench continuation/paraphrase pack for developer-work continuity pressure
- small generated benchmark outputs written under `output/` when you run the builder or benchmark locally against bounded inputs
- local-workflow code under `evals/public_corpus_wildchat_local.py` and `evals/public_corpus_wildbench_local.py`

What is not committed:
- raw WildChat or WildBench downloads
- large third-party conversation payloads
- local candidate indexes, candidate JSONL files, or review-set caches built from the full corpora
- large benchmark dumps

Repo hygiene:
- keep raw corpus files outside this repo
- keep full-corpus derived assets outside this repo
- commit only reviewed manifests, durable helper code, and reproducible local instructions

How the two sources fit together:
- keep WildChat as the primary realism corpus for messy agent-mediated carry-forward and no-value suppression
- use WildBench as a complementary benchmark source for realistic external task prompts and paraphrased follow-ups
- do not treat WildBench as a replacement for WildChat or as a second ingestion platform
- keep the failure taxonomy shared so both sources report the same categories:
  - retrieval recall
  - routing/layer choice
  - result packaging/evidence
  - compact task-state where applicable
  - no-value overreach

WildChat notes:
- use the official dataset card for license and terms review before downloading locally: `https://huggingface.co/datasets/allenai/WildChat-4.8M`
- filter aggressively: explicit English, safe/non-toxic when metadata is present, and multi-turn only

Recommended local WildChat directory convention:
- `C:\data\wildchat\WildChat-4.8M\snapshot`: raw Hugging Face snapshot
- `C:\data\wildchat\WildChat-4.8M\derived\conversation_index.sqlite`: local filtered-conversation index for slice review
- `C:\data\wildchat\WildChat-4.8M\derived\review_candidates.jsonl`: candidate episodes to review before updating the committed manifest
- `C:\data\wildchat\WildChat-4.8M\derived\review_sets\wildchat_review_manifest\`: materialized small corpus and reviewed episodes for repeated benchmark runs
- `C:\data\wildchat\WildChat-4.8M\runs\`: benchmark outputs

WildChat one-time setup:
```powershell
.\.venv\Scripts\python.exe -m pip install huggingface_hub pyarrow
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local download --root C:\data\wildchat\WildChat-4.8M
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local validate --root C:\data\wildchat\WildChat-4.8M
```

Cut reviewed-slice candidates from the full local WildChat corpus, then review them into a manifest with real conversation ids:
```powershell
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local build-candidate-index --root C:\data\wildchat\WildChat-4.8M
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local emit-candidates --root C:\data\wildchat\WildChat-4.8M
```

After review, materialize that slice into a small local cache and benchmark it repeatedly:
```powershell
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local materialize-review-set --root C:\data\wildchat\WildChat-4.8M --reviewed-manifest evals\public_corpus\wildchat_review_manifest.json
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local benchmark --root C:\data\wildchat\WildChat-4.8M --reviewed-manifest evals\public_corpus\wildchat_review_manifest.json --run-name local-public-corpus-benchmark
```

WildBench notes:
- use the official dataset card for license and terms review before downloading locally: `https://huggingface.co/datasets/allenai/WildBench`
- WildBench is already benchmark-shaped, so keep the local helper small: reviewed candidate emission, reviewed-set materialization, repeated benchmark runs, and small committed continuation packs when they add real signal
- use it to pressure realistic external task prompts and paraphrased follow-ups, not to replace WildChat’s carry-forward realism slice

Recommended local WildBench directory convention:
- `C:\data\wildbench\WildBench\snapshot`: raw Hugging Face snapshot
- `C:\data\wildbench\WildBench\derived\review_candidates.jsonl`: candidate episodes to review before updating the committed manifest
- `C:\data\wildbench\WildBench\derived\review_sets\wildbench_review_manifest\`: materialized small corpus and reviewed episodes for repeated benchmark runs
- `C:\data\wildbench\WildBench\runs\`: benchmark outputs

WildBench one-time setup:
```powershell
.\.venv\Scripts\python.exe -m pip install huggingface_hub pyarrow
.\.venv\Scripts\python.exe -m evals.public_corpus_wildbench_local download --root C:\data\wildbench\WildBench
.\.venv\Scripts\python.exe -m evals.public_corpus_wildbench_local validate --root C:\data\wildbench\WildBench
```

Emit review candidates from the local WildBench snapshot:
```powershell
.\.venv\Scripts\python.exe -m evals.public_corpus_wildbench_local emit-candidates --root C:\data\wildbench\WildBench
```

After review, materialize the reviewed slice and benchmark it:
```powershell
.\.venv\Scripts\python.exe -m evals.public_corpus_wildbench_local materialize-review-set --root C:\data\wildbench\WildBench --reviewed-manifest evals\public_corpus\wildbench_review_manifest.json
.\.venv\Scripts\python.exe -m evals.public_corpus_wildbench_local benchmark --root C:\data\wildbench\WildBench --reviewed-manifest evals\public_corpus\wildbench_review_manifest.json --run-name local-public-corpus-wildbench-benchmark
```

Notes:
- `evals.public_corpus_builder` and `evals.public_corpus_benchmark` now work for both WildChat and WildBench reviewed-manifest inputs
- for the larger WildChat corpus, prefer the WildChat local helper so repeated benchmark runs reuse a materialized review-set cache instead of rescanning the raw snapshot each time
- for WildBench, keep the workflow small and benchmark-focused; do not build a broader multi-corpus platform in this phase



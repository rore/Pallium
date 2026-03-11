# Public Corpus Eval Assets

This directory stores reviewed metadata for the public real-interaction eval slice.

What is committed:
- `wildchat_review_manifest.json`: reviewed episode selections and labels for the first WildChat-backed benchmark slice
- small generated benchmark outputs written under `output/` when you run the builder or benchmark locally

What is not committed:
- raw WildChat downloads or exported dumps
- large third-party conversation payloads

Repo hygiene:
- keep raw corpus files outside the repo and point the builder/benchmark at a local export path
- commit only reviewed manifests, derived small assets, and reproducible local instructions

WildChat notes:
- use WildChat as the only required corpus for this first slice
- filter aggressively: explicit English, safe/non-toxic when metadata is present, and multi-turn only
- verify the current upstream WildChat license and terms on the official dataset card before downloading locally

Suggested local export workflow:
1. Download or export a local WildChat JSONL file outside this repo.
2. Build reviewed episodes from the local export:
```powershell
.\.venv\Scripts\python.exe -m evals.public_corpus_builder --corpus-file C:\data\wildchat.jsonl --reviewed-manifest evals\public_corpus\wildchat_review_manifest.json --emit-candidates
```
3. Run the reviewed benchmark against that same local export:
```powershell
.\.venv\Scripts\python.exe -m evals.public_corpus_benchmark --corpus-file C:\data\wildchat.jsonl --reviewed-manifest evals\public_corpus\wildchat_review_manifest.json
```

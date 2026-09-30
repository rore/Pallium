# Behavioral contracts

This directory contains Pallium's accepted, caller-visible product obligations. Its
tests run in the existing PR `test` job. A failure is visible; workflow protection
requires classification of edits but does not block a GitHub merge.

Add one test for a distinct obligation only when its docstring names the authoritative
product source and concrete failure class, the test drives an HTTP/MCP/hook caller
surface and checks the public read result, a historical or controlled-fault witness
shows the assertion fails, and the test is deterministic on every PR. Keep fixtures
local and anonymized. Do not move broad implementation-test files here or treat
internal state, queue submission, or a renamed prompt as the product outcome.

Organize tests by product area in `test_*.py` modules; keep requirement provenance
beside each test instead of maintaining a second test inventory here. Existing
mixed-purpose tests remain useful evidence outside this directory. To run the
protected suite locally:

```powershell
python -m pytest tests/behavior_contracts/ -q -n 0
```

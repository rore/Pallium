# blue-zone-work

You're in blue-zone work. The agent moves with high autonomy here; tests and normal review are sufficient. The base rules are in `operating-mode.md`.

## What blue zone is for

Blue zone is where agent autonomy is the point. Use it. Don't artificially slow down to "verify" what the policy already classified as safe.

## Watch for zone leakage during work

A task that started in blue can drift into red as it grows. Signals:

- A new import you're about to add crosses a layer (operating-mode boundary risk applies — re-classify)
- A "small refactor" turns out to touch a shared abstraction
- A test you're writing requires changes to production code in a different zone

When you notice the drift, stop and re-classify. Don't push through and surface it later.

## Tests are the safety net, not a checkbox

Blue zone autonomy is contingent on tests catching regressions. If you find yourself working in blue zone with weak tests, the right move is to add tests as part of the work — not skip them because the change "feels safe."

## Do not over-pad

Blue zone PR descriptions are the smallest cases of `pr-discipline.md`'s rules. Don't write three paragraphs to describe a one-file change. The reviewer should be able to merge in seconds.

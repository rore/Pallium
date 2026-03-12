# Work Resumption Benchmark Report

Run ID: `local-work-resumption-stub`

## Scenario Families Added

- `debugging_continued_from_partial_findings`
- `no_value_continuation_guard`
- `resumed_after_auth_or_tool_failure`
- `resumed_implementation_after_interruption`
- `resumed_investigation_after_pause`

## Scoring Dimensions

- `task_orientation`
- `prior_findings_reused`
- `blocker_state`
- `preserved_progress`
- `next_step_guidance`

## Aggregate

- scenarios: 5
- value scenarios: 4
- non-value scenarios: 1
- memory-backed wins: 4 / 4
- top-layer matches: 5 / 5
- non-value guard successes: 1 / 1
- biggest gap: compact_task_state_memory
- implication: The next feature should add a compact task-state memory that carries forward progress, blocker state, and the next step without depending on transcript replay.

## Gap Signals

- `compact_task_state_memory`: 4
- `selected_work_artifact_support`: 1

## Scenario Results

- `resume-investigation-after-pause`: winner `memory_backed`, top layer `lower_level_memory`, missing after memory none, gap signals none
- `debugging-continued-from-partial-findings`: winner `memory_backed`, top layer `lower_level_memory`, missing after memory ['preserved_progress', 'next_step_guidance'], gap signals ['compact_task_state_memory']
- `resume-after-auth-tool-failure`: winner `memory_backed`, top layer `source_evidence`, missing after memory ['preserved_progress', 'next_step_guidance'], gap signals ['compact_task_state_memory', 'selected_work_artifact_support']
- `resume-implementation-ticket-after-interruption`: winner `memory_backed`, top layer `lower_level_memory`, missing after memory ['next_step_guidance'], gap signals ['compact_task_state_memory']
- `same-thread-no-value-continuation`: winner `baseline`, top layer `source_evidence`, missing after memory none, gap signals none

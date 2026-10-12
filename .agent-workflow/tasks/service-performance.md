# Service-wide performance investigation and correction

<!-- agent-workflow:start -->
**Outcome:** Investigate service-wide performance and correct measured bottlenecks so the service remains responsive and correct under representative concurrent and background workloads; do not claim universal absence of performance issues before evidence.

**Target:** Pallium service, isolated baseline cf5581147d9a1e1ec8ac73e8e8d186fb948a4269.

**Scope:** Initialize only .agent-workflow/tasks/service-performance.md on fix/service-performance from cf5581147d9a1e1ec8ac73e8e8d186fb948a4269. Service-wide read-only discovery covers HTTP/MCP request latency, event-loop blocking, database/query/writer contention and background/runtime lifecycle work. Exact production and test fix paths and resource limits must be derived from measurements and independently reviewed before edits. The separate service-async-startup task remains unfinished; preserve its record and coordinate any overlap rather than duplicating its implementation. Root owns canonical roadmap reconciliation in the shared main checkout; no roadmap edit by this worker.

**Constraints:** No production, test, roadmap, configuration, installed environment, live database/load or service-restart changes in this initialization slice. Preserve caller-visible validation, scope/isolation, delivery/claim/ACK/generation fences, cancellation/restart cleanup, persistence semantics and supported package boundaries. No new framework, arbitrary timeout/capacity increase, hidden retry, skipped assertions or weakened correctness contract as a performance fix. Reuse existing isolated evidence and runners; root coordinates execution, exact scope review, one coherent selected/full qualification, integration and any separately authorized rollout. No push by this worker.

**Completion criteria:** Publish a measured service-wide bottleneck inventory with causal attribution and prioritized minimal fix slices. Cover same-endpoint and many-endpoint workloads at 1/10/25/50 concurrency, growing delivered history, active background work and cancellation/restart interactions. Record latency p50/p95/max, throughput, query and writer-admission counts and resource/queue evidence; observable payload delivery must have zero loss, duplicate or cross-scope violations. Each implemented fix needs a failing-before/passing-after caller-surface regression and comparable isolated measurements with preserved budgets/contracts. Complete independent technical plan/result review, whole-change selected/full validation and root-owned roadmap/docs reconciliation before declaring the measured scope complete; disclose remaining limits and unmeasured scenarios.

**Requirement baseline:**
{"source":"direct human source 0742db7b-c8f4-4ecb-9ca8-a046a4bc6741 on 2026-10-12, root thread 01a0d7ce-83c6-77e2-90f7-d413894059e1; exact message timestamp not supplied","outcome":"Investigate service-wide performance and correct measured bottlenecks so the service remains responsive and correct under representative concurrent and background workloads; do not claim universal absence of performance issues before evidence.","scope":"Initialize only .agent-workflow/tasks/service-performance.md on fix/service-performance from cf5581147d9a1e1ec8ac73e8e8d186fb948a4269. Service-wide read-only discovery covers HTTP/MCP request latency, event-loop blocking, database/query/writer contention and background/runtime lifecycle work. Exact production and test fix paths and resource limits must be derived from measurements and independently reviewed before edits. The separate service-async-startup task remains unfinished; preserve its record and coordinate any overlap rather than duplicating its implementation. Root owns canonical roadmap reconciliation in the shared main checkout; no roadmap edit by this worker.","constraints":"No production, test, roadmap, configuration, installed environment, live database/load or service-restart changes in this initialization slice. Preserve caller-visible validation, scope/isolation, delivery/claim/ACK/generation fences, cancellation/restart cleanup, persistence semantics and supported package boundaries. No new framework, arbitrary timeout/capacity increase, hidden retry, skipped assertions or weakened correctness contract as a performance fix. Reuse existing isolated evidence and runners; root coordinates execution, exact scope review, one coherent selected/full qualification, integration and any separately authorized rollout. No push by this worker.","completion_criteria":"Publish a measured service-wide bottleneck inventory with causal attribution and prioritized minimal fix slices. Cover same-endpoint and many-endpoint workloads at 1/10/25/50 concurrency, growing delivered history, active background work and cancellation/restart interactions. Record latency p50/p95/max, throughput, query and writer-admission counts and resource/queue evidence; observable payload delivery must have zero loss, duplicate or cross-scope violations. Each implemented fix needs a failing-before/passing-after caller-surface regression and comparable isolated measurements with preserved budgets/contracts. Complete independent technical plan/result review, whole-change selected/full validation and root-owned roadmap/docs reconciliation before declaring the measured scope complete; disclose remaining limits and unmeasured scenarios."}

**Risk:** High

**Complexity:** Large

**Reason:** Provisional whole-task classification anticipates persistence, API and lifecycle surfaces with independently verifiable outcomes. Redline makes persistence/API/core contracts RED and runtime layers gray/watch; architecture/API/persistence checkpoints and separate human attention may apply to measured fix paths. No boundary violation or schema/API requirement change is assumed or approved. Reclassify against exact derived paths before editing.

**Discovery:** Root has initiated read-only parallel discovery: architecture_check reviews service-wide blocking, database and background behavior; incident_integration_review decomposes request latency; pal-dev1 offered an isolated remeasurement of the existing database audit, pending acceptance. Reports and new causal measurements are not yet available in this record. The cf558114 baseline contains the previous bounded Relay corrections and qualification; that evidence does not establish service-wide performance or behavior at growing history/same-endpoint contention. The separate service-async-startup record remains unfinished, with its owner and original scope preserved.

**Material assumptions:** A representative isolated workload can distinguish event-loop, client-pool, executor/registry, SQL writer/query and background costs; missing phase evidence requires better attribution before proposing a source fix. Same-endpoint and many-endpoint behavior and growing history may differ; measure both rather than extrapolating one workload. Native transport simulation and private data are limited proxies and must be named; no installed qualification is inferred. Latency budgets and candidate fix paths remain to be derived, not guessed. The user's broad objective is authorized; incomplete evidence/plan, not missing user permission, is the current planning gate.

**Plan:** Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. Done before this planning record: loaded repo workflow/applicability/Redline/behavioral-integrity instructions, invoked native Codex workflow seed and created the isolated branch. Current implementation plan is incomplete and returned to planning: collect existing owners' reports and comparable isolated measurements first; map each confirmed cost to exact caller paths, lifecycle/compatibility constraints and minimal correction candidates; coordinate with the unfinished startup owner; then record exact scope, resource budgets, causal regressions and independent technical review before production/test edits. Implement only reviewed coherent slices using existing capabilities, rerun comparable measurements and relevant E2E, then run the whole-change selector and required full lane once with root. Stop/replan on violated attribution, correctness or scope assumptions. This record does not authorize a guessed fix or duplicate startup implementation.

**Verification plan:**
Service responsiveness under 1/10/25/50 same/many-endpoint concurrency -> existing isolated HTTP/MCP/hook surfaces with separate health client, per-phase p50/p95/max, throughput and query/writer-admission counts.
History growth and active background amplification -> comparable private datasets and enabled existing background paths, with SQL plans/counts and bounded thread/queue evidence.
Cancellation/restart and exact correctness -> caller-surface lifecycle regressions/public readback showing zero payload loss/duplicate/cross-scope violations with unchanged fences and deadlines.
Each measured fix -> causal RED/GREEN plus baseline/candidate comparisons, focused serial checks and affected subsystem validation; exact nodes/files derive from discovery before edits.
Whole-change assurance -> fresh Redline/import-boundary and Agent Workflow checks, scripts/test-plan.py --base origin/main, required full/CI and independent plan/result review; root owns shared-main roadmap reconciliation and separate live rollout.
Any retrieval/eval metric -> identify candidate-recovery, injection-precision or downstream-task-effect and preserve the invariant that retrieval alone does not update accessibility state.

**Plan review:** Pending a concrete implementation plan and independent non-implementer review after measurements. architecture_check's assigned discovery is not a completed plan GO. No implementation-ready or result approval is claimed.

**Approvals:** Approved by user 2026-10-12: "Okay, the point was to make sure we don't have any performance issues. We need to find, analyze, find all our performance problems and make sure we handle everything. The service should function optimized without any bottlenecks." Exact direct human source 0742db7b-c8f4-4ecb-9ca8-a046a4bc6741 supplied by root; date only, no invented message timestamp. This authorizes the service-wide investigation and correction objective, not a claim that the human approved an unseen concrete plan or new live environment changes. Current return to planning is due to measurement and scope derivation, not a user-approval blocker.

**Exceptions:** None

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Applicability and initialization

2026-10-12: Agent Workflow applies to this implementation-plan/performance-fix task. The whole task is not documentation-only; intended production/test paths are incomplete pending discovery, and Work Records themselves are never exempt. No documentation exemption or direct-default-branch eligibility is claimed. Provisional High/Large classification follows the actual policy plus conservative service-wide persistence/API/lifecycle risk; exact source paths and fresh deterministic verdict must be derived before edits. Initial checkout was clean/detached at cf5581147d9a1e1ec8ac73e8e8d186fb948a4269; branch fix/service-performance created after workflow invocation. Only this planning record is written.

## Parallel discovery and recovery

| Owner | Current bounded assignment |
|---|---|
| architecture_check | Service-wide blocking/database/background read-only review |
| incident_integration_review | Request latency decomposition |
| pal-dev1 | Offered isolated existing DB-audit remeasurement; pending acceptance |
| root | Integration, priorities, exact-scope disposition, execution coordination and canonical roadmap ownership |
| discovery_contract_review | Initialize planning record/branch only |

Existing service-async-startup is a separate unfinished task. Do not overwrite its record, silently adopt its dirty work or duplicate its implementation. Ask its owner/root to coordinate only concrete overlap when a measured slice reaches that surface. No exact roadmap item reference was supplied; none invented.

## Evidence

No new application test, performance/load run, live inspection/change, restart or production/test edit performed by this initializer. Native Codex workflow seed succeeded; classification/config and request-scope applicability were read before the planning record. Measurements, numeric targets, candidate fixes and independent review are pending. Reuse prior reliable artifacts only with their revision, workload and simulation limits; do not describe prior Relay qualification as proof that all service bottlenecks are resolved.

## Result review and next action

Not implementation-ready. The next owner first collects the assigned discovery/latency reports and accepted isolated measurements, then writes exact fix paths, budgets, causal verification and plan review before edits. Human authorization remains available for the stated objective; do not request it again merely because discovery is unfinished. Root owns any roadmap reconciliation. Preserve this isolated checkout and WR-first history for the task; no push or deployment by this initializer.


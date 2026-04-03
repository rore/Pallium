from __future__ import annotations

import json

from providers.llm.base import LLMJsonResponse


class TieredMemorySemanticProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if 'task_checkpoint' in schema_description and 'Thread items:' in user_prompt:
            summary_payload = _build_thread_summary_payload(user_prompt)
            checkpoint_payload = _build_task_checkpoint_payload(user_prompt)
            merged = dict(summary_payload)
            merged.setdefault('content_quality', 'substantive')
            merged['task_checkpoint'] = checkpoint_payload
            return LLMJsonResponse(raw_text=json.dumps(merged), parsed_json=merged)
        if 'freshness_signal' in schema_description:
            payload = _build_task_checkpoint_payload(user_prompt)
        elif 'carry_forward_answer' in schema_description:
            payload = _build_continuity_payload(user_prompt)
        elif 'pattern_label' in schema_description:
            payload = _build_pattern_payload(user_prompt)
        elif 'Thread items:' in user_prompt:
            payload = _build_thread_summary_payload(user_prompt)
            payload.setdefault('content_quality', 'substantive')
        else:
            payload = _build_item_extraction_payload(user_prompt)
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


class TieredMemoryAnswerProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        payload = _build_answer_payload(user_prompt)
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)

def _build_write_enrichment_payload(user_prompt: str) -> dict[str, object]:
    lower = user_prompt.lower()
    if 'record type: task_checkpoint' in lower and 'batch 313' in lower:
        return {
            'action': 'ENRICH',
            'retrieval_context': 'Catalog sync retry resume state anchored on the batch 313 restart after service-token failure.',
        }
    if 'record type: thread_summary' in lower and 'lib-241' in lower:
        return {
            'action': 'ENRICH',
            'retrieval_context': 'Flag-gated LIB-241 reservation ordering rollout with remaining admin-toggle and retry-path coverage work.',
        }
    if 'record type: pattern_memory' in lower and 'duplicate holds' in lower:
        return {
            'action': 'ENRICH',
            'retrieval_context': 'Cross-thread reservation ordering lesson about duplicate holds after catalog sync delays.',
        }
    if 'record type: continuity_memory' in lower and '30-minute batches' in lower:
        return {
            'action': 'ENRICH',
            'retrieval_context': 'Carry-forward answer for overdue notice batching and staff inbox spam questions.',
        }
    if 'record type: continuity_memory' in lower:
        return {
            'action': 'ENRICH',
            'retrieval_context': 'Carry-forward answer for a repeated question from the same conversation thread.',
        }
    return {
        'action': 'NO_OP',
        'retrieval_context': None,
    }


def _build_inventory_batch_thread_summary_payload(lower: str) -> dict[str, str] | None:
    if 'export manifest locally after the workspace timeout' in lower and 'refresh the local export token' in lower:
        return {
            'summary': 'The newer compatible catalog export status kept the local validation progress, and the next step is to refresh the local export token and rerun validation from batch 313.'
        }
    if (
        (
            ('inventory batch digest' in lower and 'bin-103' in lower)
            or ('batch digest' in lower and 'slot-103' in lower)
        )
        and ('local browser' in lower or 'browser sign-in' in lower or 'control-panel sign-in' in lower)
    ):
        return {
            'summary': 'The thread preserved the batch digest context for the staged segments, and the standing restriction is to avoid control-panel sign-in or browser sign-in.'
        }
    if ('channel filters' in lower and 'authentication is restored' in lower) or ('manifest filters' in lower and 'authentication is restored' in lower):
        return {
            'summary': 'The thread preserved the batch digest blocker, noted that the remote mirror was unauthenticated, and suggested retrying the digest after authentication is restored.'
        }
    if ('mirror-based batch digest' in lower or 'mirrored batch digest' in lower) and (
        'attempt to authenticate to the operations portal' in lower or 'attempt control-panel sign-in' in lower
    ):
        return {
            'summary': 'The thread captured the newer batch digest blocker and suggested attempting control-panel sign-in before retrying the digest.'
        }
    if (
        ('sign in to the operations portal manually' in lower or 'attempt control-panel sign-in' in lower)
        and ('local browser' in lower or 'browser sign-in' in lower)
        and 'retry after authentication is restored' in lower
    ):
        return {
            'summary': 'The thread repeated the no-login restriction, but also preserved contradictory authentication-retry guidance.'
        }
    return None


def _build_wallet_thread_summary_payload(lower: str) -> dict[str, str] | None:
    if ('wallet reserve snapshot' in lower and 'wal-102' in lower and 'publish the wallet reserve note' in lower) or (
        'reserve snapshot' in lower and 'pouch-102' in lower and 'publish the reserve note' in lower
    ):
        return {
            'summary': 'The thread preserved the reserve snapshot, and the next step is to publish the reserve note after confirming the local snapshot.'
        }
    return None



def _build_wallet_task_checkpoint_payload(lower: str) -> dict[str, object] | None:
    if ('wallet reserve snapshot' in lower and 'wal-102' in lower and 'publish the wallet reserve note' in lower) or (
        'reserve snapshot' in lower and 'pouch-102' in lower and 'publish the reserve note' in lower
    ):
        return {
            'summary': 'The reserve snapshot is ready for the local review.',
            'task': 'Resume the reserve snapshot review.',
            'current_state': 'The reserve snapshot is reconciled for the tracked pouches.',
            'key_findings': [
                'The reserve snapshot is reconciled for the tracked pouches.',
                'The reserve note still needs local snapshot confirmation before publication.',
            ],
            'blocker_state': '',
            'next_step': 'Publish the reserve note after confirming the local snapshot.',
            'evidence': [
                'Partial progress: the reserve snapshot is reconciled for the tracked pouches.',
                'Next step: publish the reserve note after confirming the local snapshot.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T12:35:00Z.',
        }
    return None



def _build_inventory_batch_task_checkpoint_payload(lower: str) -> dict[str, object] | None:
    if 'export manifest locally after the workspace timeout' in lower and 'refresh the local export token' in lower:
        return {
            'summary': 'The newer compatible catalog export status is ready for the next local retry step.',
            'task': 'Resume the catalog sync retry.',
            'current_state': 'Validated the export manifest locally after the workspace timeout.',
            'key_findings': [
                'The export manifest was validated locally after the workspace timeout.',
                'The next safe retry still uses the local export token and resume point at batch 313.',
            ],
            'blocker_state': '',
            'next_step': 'Refresh the local export token and rerun the validation from batch 313.',
            'evidence': [
                'Partial progress: validated the export manifest locally after the workspace timeout.',
                'Next step: refresh the local export token and rerun the validation from batch 313 without using the admin portal or a local browser.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T11:12:00Z.',
        }
    if (
        (
            ('inventory batch digest' in lower and 'bin-103' in lower)
            or ('batch digest' in lower and 'slot-103' in lower)
        )
        and ('local browser' in lower or 'browser sign-in' in lower or 'control-panel sign-in' in lower)
    ):
        return {
            'summary': 'The batch digest is preserved with an explicit no-login restriction.',
            'task': 'Resume the batch digest.',
            'current_state': 'The batch digest is prepared for the staged segments.',
            'key_findings': [
                'The batch digest already covers the staged segments.',
                'Do not use control-panel sign-in or open a browser sign-in flow.',
            ],
            'blocker_state': 'The operator restriction forbids control-panel sign-in and browser sign-in during this batch digest work.',
            'next_step': 'Refresh the local digest token and rerun the batch digest from the last confirmed segment.',
            'evidence': [
                'Partial progress: prepared the batch digest for the staged segments.',
                'Constraint: do not use control-panel sign-in and do not open a browser sign-in flow.',
                'Next step: refresh the local digest token and rerun the batch digest from the last confirmed segment.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
        }
    if ('channel filters' in lower and 'authentication is restored' in lower) or ('manifest filters' in lower and 'authentication is restored' in lower):
        return {
            'summary': 'Older batch digest work is blocked by missing authentication.',
            'task': 'Resume the batch digest after the auth blocker is resolved.',
            'current_state': 'Manifest filters and digest scheduling are ready, but the remote mirror is unauthenticated.',
            'key_findings': [
                'Manifest filters and digest scheduling are staged.',
                'The remote mirror is unauthenticated.',
            ],
            'blocker_state': 'The batch digest cannot proceed until authentication is restored for the remote mirror.',
            'next_step': 'Retry the batch digest after authentication is restored.',
            'evidence': [
                'Partial progress: manifest filters and digest scheduling are staged.',
                'Blocked: the batch digest is unauthenticated for the remote mirror.',
                'Next step: retry the batch digest after authentication is restored.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T11:02:00Z.',
        }
    if ('mirror-based batch digest' in lower or 'mirrored batch digest' in lower) and (
        'attempt to authenticate to the operations portal' in lower or 'attempt control-panel sign-in' in lower
    ):
        return {
            'summary': 'A newer batch digest is blocked by remote authentication.',
            'task': 'Resume the newer batch digest.',
            'current_state': 'The newer batch digest is prepared, but remote authentication still blocks it.',
            'key_findings': [
                'The newer batch digest is prepared for the staged manifests.',
                'Remote authentication still blocks it.',
            ],
            'blocker_state': 'The newer batch digest cannot proceed until remote authentication succeeds.',
            'next_step': 'Attempt control-panel sign-in and auxiliary-console sign-in before retrying the batch digest.',
            'evidence': [
                'Partial progress: built the mirrored batch digest for the staged manifests.',
                'Blocked: the mirrored batch digest cannot proceed until remote authentication succeeds.',
                'Next step: attempt control-panel sign-in and auxiliary-console sign-in before retrying the batch digest.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T12:02:00Z.',
        }
    if (
        ('sign in to the operations portal manually' in lower or 'attempt control-panel sign-in' in lower)
        and ('local browser' in lower or 'browser sign-in' in lower)
        and 'retry after authentication is restored' in lower
    ):
        return {
            'summary': 'The batch digest thread mixed an explicit no-login restriction with contradictory authentication-retry guidance.',
            'task': 'Resume the batch digest after the current failure.',
            'current_state': 'The batch digest summary is ready, and the thread repeated the no-login restriction.',
            'key_findings': [
                'Do not use control-panel sign-in or open a browser sign-in flow.',
                'The draft also said to attempt control-panel sign-in and retry after authentication is restored.',
            ],
            'blocker_state': 'The thread says not to use control-panel sign-in or browser sign-in, but also says the next step depends on authentication retry.',
            'next_step': 'Attempt control-panel sign-in, provide a reference code, and retry after authentication is restored.',
            'evidence': [
                'Constraint: do not use control-panel sign-in and do not open a browser sign-in flow.',
                'Next step: attempt control-panel sign-in, provide a reference code, and retry after authentication is restored.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T13:05:00Z.',
        }
    return None

def _build_item_extraction_payload(user_prompt: str) -> dict[str, object]:
    lower = user_prompt.lower()
    if any(
        phrase in lower
        for phrase in (
            'task complete. no slack message needed. nothing new to report.',
            'task complete. nothing new to report.',
            'no response requested. nothing new to report.',
            'understood. no browser auth, no portal or console auth. i will use the local cache only.',
        )
    ) or (
        ('i will use the local repos only' in lower or 'i will use the local cache only' in lower)
        and ('auth' in lower or 'authentication' in lower)
    ):
        return {
            'summary': 'Low-value orchestration update.',
            'candidate_type': None,
            'decision_text': None,
            'decision_evidence_text': None,
            'investigation_text': None,
            'investigation_evidence_text': None,
            'rationale_text': None,
            'is_low_value_meta': True,
            'constraint_text': None,
            'next_step_text': None,
            'blocker_text': None,
            'progress_text': None,
            'key_finding_text': None,
        }

    if 'Decision:' in user_prompt:
        decision_text = _extract_after_marker(user_prompt, 'Decision:')
        rationale_text = None
        if ' to ' in decision_text:
            prefix, suffix = decision_text.split(' to ', 1)
            decision_text = prefix.strip()
            rationale_text = f"to {suffix.strip()}"
        return {
            'summary': 'Decision recorded in the conversation.',
            'candidate_type': 'decision',
            'decision_text': decision_text.strip(),
            'decision_evidence_text': f"Decision: {decision_text.strip()}" if not decision_text.lower().startswith('decision:') else decision_text,
            'investigation_text': None,
            'investigation_evidence_text': None,
            'rationale_text': rationale_text,
        }

    if 'Investigation found' in user_prompt:
        finding = _extract_sentence_containing(user_prompt, 'Investigation found')
        finding = finding.replace('Investigation found that ', '').replace('Investigation found ', '').strip().rstrip('.')
        return {
            'summary': 'Investigation outcome recorded in the conversation.',
            'candidate_type': 'investigation_outcome',
            'decision_text': None,
            'decision_evidence_text': None,
            'investigation_text': finding,
            'investigation_evidence_text': _extract_sentence_containing(user_prompt, 'Investigation found').strip(),
            'rationale_text': None,
        }

    if 'got through batch 417' in lower and 'resume from batch 418' in lower:
        return {
            'summary': 'Natural-language resumed-work state recorded in the conversation.',
            'candidate_type': None,
            'decision_text': None,
            'decision_evidence_text': None,
            'investigation_text': None,
            'investigation_evidence_text': None,
            'rationale_text': None,
            'is_low_value_meta': False,
            'constraint_text': None,
            'next_step_text': 'Wait 15 minutes and resume from batch 418.',
            'blocker_text': 'The retry window is exhausted now.',
            'progress_text': 'The token refresh worked and the sync got through batch 417.',
            'key_finding_text': None,
        }

    if 'admin toggle wiring is ready' in lower and 'fallback coverage is still missing' in lower:
        return {
            'summary': 'Natural-language review state recorded in the conversation.',
            'candidate_type': None,
            'decision_text': None,
            'decision_evidence_text': None,
            'investigation_text': None,
            'investigation_evidence_text': None,
            'rationale_text': None,
            'is_low_value_meta': False,
            'constraint_text': None,
            'next_step_text': None,
            'blocker_text': 'Branch kiosk fallback coverage is still missing before review can pass.',
            'progress_text': 'The admin toggle wiring is ready.',
            'key_finding_text': None,
        }

    if 'lower concurrency or bump memory' in lower and 'confirm which worker' in lower:
        return {
            'summary': 'Tentative guidance without durable work state.',
            'candidate_type': None,
            'decision_text': None,
            'decision_evidence_text': None,
            'investigation_text': None,
            'investigation_evidence_text': None,
            'rationale_text': None,
            'is_low_value_meta': False,
            'constraint_text': None,
            'next_step_text': None,
            'blocker_text': None,
            'progress_text': None,
            'key_finding_text': None,
        }

    # Interest detection: user expresses specific future-oriented interest (user role only)
    interest_markers = ('sounds interesting', 'should check', 'worth looking into', 'may be worth', 'want to look into', 'want to try')
    if any(marker in lower for marker in interest_markers) and 'Role: assistant' not in user_prompt:
        # Extract the subject from the content — use the first noun-like phrase before the marker
        interest_subject = user_prompt.strip().split('.')[0].strip()
        return {
            'summary': f'User expresses interest: {interest_subject}',
            'candidate_type': 'interest',
            'interest_text': interest_subject,
            'decision_text': None,
            'decision_evidence_text': None,
            'investigation_text': None,
            'investigation_evidence_text': None,
            'rationale_text': None,
        }

    # Constraint detection: definitive constraints only, not tentative preferences.
    # Hedging markers suppress constraint extraction regardless of content.
    _TENTATIVE_MARKERS = ('i think', 'maybe', 'probably', 'leaning towards', 'leaning toward',
                          'not sure', 'i was thinking', "i'd prefer", 'we could probably')
    _DEFINITIVE_MARKERS = ('do not', "don't", 'must', 'cannot', 'non-negotiable', 'has to',
                           'have to', 'not going', 'no external', 'absolutely cannot',
                           'not allowed', 'all data must')
    is_tentative = any(marker in lower for marker in _TENTATIVE_MARKERS)
    has_definitive = any(marker in lower for marker in _DEFINITIVE_MARKERS)
    if has_definitive and not is_tentative and 'Role: assistant' not in user_prompt:
        # Extract a short constraint summary from the content
        content_line = user_prompt.strip().split('\n')[-1].strip()
        # Find the content after "Content:" if present
        if 'Content:' in user_prompt:
            content_line = user_prompt.split('Content:', 1)[1].strip().split('\n')[0].strip()
        return {
            'summary': 'Constraint recorded in the conversation.',
            'candidate_type': None,
            'decision_text': None,
            'decision_evidence_text': None,
            'investigation_text': None,
            'investigation_evidence_text': None,
            'rationale_text': None,
            'is_low_value_meta': False,
            'constraint_text': content_line,
            'constraint_candidates': [{'constraint_text': content_line}],
            'next_step_text': None,
            'blocker_text': None,
            'progress_text': None,
            'key_finding_text': None,
        }

    return {
        'summary': 'Conversation summary.',
        'candidate_type': None,
        'decision_text': None,
        'decision_evidence_text': None,
        'investigation_text': None,
        'investigation_evidence_text': None,
        'rationale_text': None,
    }


def _build_thread_summary_payload(user_prompt: str) -> dict[str, str]:
    lower = user_prompt.lower()
    inventory_batch = _build_inventory_batch_thread_summary_payload(lower)
    if inventory_batch is not None:
        return inventory_batch
    wallet_snapshot = _build_wallet_thread_summary_payload(lower)
    if wallet_snapshot is not None:
        return wallet_snapshot
    if 'branch kiosk fallback' in lower and 're-request review' in lower:
        return {
            'summary': 'The thread kept the use_item_event_time flag off for branch kiosks, confirmed the admin toggle wiring was ready, and still needs branch kiosk fallback coverage before review can pass.'
        }
    if 'retry window was exhausted' in lower and 'batch 418' in lower:
        return {
            'summary': 'The latest catalog sync retry resumed after auth refresh, but is now blocked by a 429 retry-window limit and should resume from batch 418 after waiting 15 minutes.'
        }
    if 'notify_digest_v2' in lower and 'scheduled-job backoff' in lower:
        return {
            'summary': 'Ticket LIB-314 kept the notification digest fix behind notify_digest_v2 and still needs scheduled-job backoff before enablement.'
        }
    if 'investigation found' in lower and 'decision:' in lower:
        return {
            'summary': 'The thread found that arrival-time ordering caused hold problems during catalog sync delays and decided to use item event time ordering.'
        }
    if 'schema change and backfill done' in lower and 'admin toggle' in lower:
        return {
            'summary': 'The thread kept the reservation ordering fix behind the use_item_event_time flag, finished the schema and backfill work, and still needs the admin toggle plus retry-path coverage.',
            'retrieval_context': 'Flag-gated LIB-241 reservation ordering rollout with remaining admin-toggle and retry-path coverage work.',
        }
    if 'service token expired' in lower and 'batch 313' in lower and 'admin portal' in lower and 'local browser' in lower:
        return {
            'summary': 'The catalog sync retry refreshed 312 reservation records before a 401 from the expired service token, and the operator constraint is to avoid admin portal sign-in or opening a local browser while resuming from batch 313.',
            'retrieval_context': 'Catalog sync retry resume state anchored on the batch 313 restart after service-token failure.',
        }
    if 'service token expired' in lower and 'batch 313' in lower:
        return {
            'summary': 'The thread refreshed 312 reservation records before a 401 caused by an expired catalog service token, and the next step is to refresh the token and resume from batch 313.',
            'retrieval_context': 'Catalog sync retry resume state anchored on the batch 313 restart after service-token failure.',
        }
    if 'reservation cache is warm' in lower and 'compare cache invalidation' in lower:
        return {
            'summary': 'The thread narrowed duplicate-hold debugging to warm-cache invalidation on delayed sync workers and should compare invalidation between delayed and immediate workers next.'
        }
    if 'investigation found' in lower:
        return {
            'summary': 'The thread found that arrival-time ordering caused hold problems during catalog sync delays.'
        }
    if '30-minute batches' in lower:
        return {
            'summary': 'The thread decided to send overdue notices in 30-minute batches to avoid staff inbox spam.'
        }
    return {'summary': 'Unresolved.', 'content_quality': 'unresolved'}


def _build_task_checkpoint_payload(user_prompt: str) -> dict[str, object]:
    lower = user_prompt.lower()
    if 'retry window was exhausted' in lower and 'batch 418' in lower:
        return {
            'summary': 'Catalog sync retry resumed after auth refresh and is now blocked by a retry-window limit.',
            'task': 'Resume the catalog sync retry from the latest blocker state.',
            'current_state': 'The token is refreshed, the sync resumed from batch 313, and the latest blocker is a 429 after batch 417.',
            'key_findings': [
                'the service token is refreshed',
                'catalog API returned 429 because the retry window was exhausted',
            ],
            'blocker_state': 'Catalog API returned 429 because the retry window was exhausted after batch 417.',
            'next_step': 'Wait 15 minutes and resume from batch 418 with the refreshed token.',
            'evidence': [
                'Progress update: the service token is refreshed and the sync resumed from batch 313.',
                'Blocked: catalog API returned 429 after batch 417 because the retry window was exhausted.',
                'Next step: wait 15 minutes, resume from batch 418, and keep the refreshed token.',
            ],
            'freshness_signal': 'The current blocker is 429 after auth refresh; the older 401 is stale.',
        }
    if 'branch kiosk fallback' in lower and 're-request review' in lower:
        return {
            'summary': 'Ticket LIB-241 review is narrowed to the missing branch kiosk fallback before the next review pass.',
            'task': 'Resume the LIB-241 review follow-up.',
            'current_state': 'The admin toggle wiring is ready, but review is still blocked on branch kiosk fallback coverage.',
            'key_findings': [
                'keep the use_item_event_time flag off for branch kiosks until retry-path coverage exists',
                'branch kiosk fallback is still missing',
            ],
            'blocker_state': 'Review is blocked because the branch kiosk fallback is still missing.',
            'next_step': 'Add the branch kiosk fallback coverage and re-request review before enabling the flag.',
            'evidence': [
                'Decision: keep the use_item_event_time flag off for branch kiosks until retry-path coverage exists.',
                'Review progress: admin toggle wiring is ready, but the branch kiosk fallback is still missing.',
                'Next step: add the branch kiosk fallback coverage and re-request review before enabling the flag.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T12:02:00+00:00.',
        }
    if 'notify_digest_v2' in lower and 'scheduled-job backoff' in lower:
        return {
            'summary': 'Ticket LIB-314 is a different work item and still needs scheduled-job backoff before enablement.',
            'task': 'Resume ticket LIB-314 for the notification digest fix.',
            'current_state': 'The UI copy and migrations are done, and notify_digest_v2 remains gated.',
            'key_findings': [
                'keep the notification digest fix behind the notify_digest_v2 flag',
                'ticket LIB-314 has the UI copy and migrations done',
            ],
            'blocker_state': '',
            'next_step': 'Wire scheduled-job backoff before enabling notify_digest_v2.',
            'evidence': [
                'Decision: keep the notification digest fix behind the notify_digest_v2 flag.',
                'Partial progress: ticket LIB-314 has the UI copy and migrations done.',
                'Next step: wire scheduled-job backoff before enabling notify_digest_v2.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T15:32:00+00:00.',
        }
    if 'service token expired' in lower and 'batch 313' in lower and 'admin portal' in lower and 'local browser' in lower:
        return {
            'summary': 'Catalog sync retry is paused at an auth failure after partial progress, with a clear restart point and an operator login constraint.',
            'task': 'Resume the catalog sync retry.',
            'current_state': 'Refreshed 312 reservation records before a 401 from the expired catalog service token; resume from batch 313 after auth is refreshed without using the admin portal or a local browser.',
            'key_findings': [
                'catalog API returned 401 because the service token expired',
                'refreshed 312 reservation records before the failure',
                'avoid admin portal sign-in and local browser use during the retry',
            ],
            'blocker_state': 'Catalog API returned 401 because the service token expired; do not use admin portal sign-in or a local browser while resolving it.',
            'next_step': 'Refresh the catalog service token and rerun the sync from batch 313.',
            'evidence': [
                'Partial progress: refreshed 312 reservation records before the catalog sync tool failed.',
                'Blocked: catalog API returned 401 because the service token expired.',
                'Constraint: do not sign in to the admin portal or open a local browser.',
                'Next step: refresh the catalog service token and rerun the sync from batch 313.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
        }
    if 'service token expired' in lower and 'batch 313' in lower:
        return {
            'summary': 'Catalog sync retry is paused at an auth failure after partial progress, with a clear restart point.',
            'task': 'Resume the catalog sync retry.',
            'current_state': 'Refreshed 312 reservation records before a 401 from the expired catalog service token; resume from batch 313 after auth is refreshed.',
            'key_findings': [
                'catalog API returned 401 because the service token expired',
                'refreshed 312 reservation records before the failure',
            ],
            'blocker_state': 'Catalog API returned 401 because the service token expired.',
            'next_step': 'Refresh the catalog service token and rerun the sync from batch 313.',
            'evidence': [
                'Partial progress: refreshed 312 reservation records before the catalog sync tool failed.',
                'Blocked: catalog API returned 401 because the service token expired.',
                'Next step: refresh the catalog service token and rerun the sync from batch 313.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00Z.',
        }
    if 'reservation cache is warm' in lower and 'compare cache invalidation' in lower:
        return {
            'summary': 'Duplicate-hold debugging already has a narrowed hypothesis, preserved progress, and a next comparison step.',
            'task': 'Resume duplicate-hold debugging on delayed sync workers.',
            'current_state': 'Local replay confirmed the bug and narrowed it to cache invalidation on delayed sync workers.',
            'key_findings': [
                'reservation cache is warm',
                'cache invalidation',
            ],
            'blocker_state': '',
            'next_step': 'Compare cache invalidation between delayed and immediate sync workers.',
            'evidence': [
                'Investigation found that duplicate holds only reproduce on delayed sync workers when the reservation cache is warm.',
                'Partial progress: local replay confirmed the bug and narrowed it to cache invalidation on delayed sync workers.',
                'Next step: compare cache invalidation between delayed and immediate sync workers.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T09:02:00Z.',
        }
    if 'schema change and backfill done' in lower and 'admin toggle' in lower:
        return {
            'summary': 'Ticket LIB-241 is partway done and can resume from the remaining flag-enable work.',
            'task': 'Resume ticket LIB-241 with the use_item_event_time flag still gated.',
            'current_state': 'The reservation ordering fix stays behind the use_item_event_time flag, and the schema change plus backfill are already done.',
            'key_findings': [
                'reservation ordering fix',
                'ticket LIB-241 has the schema change and backfill done',
            ],
            'blocker_state': '',
            'next_step': 'Wire the admin toggle and add retry-path coverage before enabling the flag.',
            'evidence': [
                'Decision: keep the reservation ordering fix behind the use_item_event_time flag.',
                'Partial progress: ticket LIB-241 has the schema change and backfill done.',
                'Next step: wire the admin toggle and add retry-path coverage before enabling the flag.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T11:02:00Z.',
        }
    return {
        'summary': 'Resume the previously recorded work from this thread.',
        'task': 'Resume the previously recorded work from this thread.',
        'current_state': '',
        'key_findings': [],
        'blocker_state': '',
        'next_step': '',
        'evidence': [],
        'freshness_signal': 'Latest explicit update time was not recorded.',
    }


def _build_pattern_payload(user_prompt: str) -> dict[str, str]:
    has_reservation = any(term in user_prompt.lower() for term in ('item event time', 'arrival-time ordering', 'duplicate holds', 'stale hold updates'))
    has_notification = '30-minute batches' in user_prompt.lower() or 'staff inbox spam' in user_prompt.lower()
    if has_reservation and has_notification:
        return {
            'summary': 'A mixed pattern mentions reservation ordering during sync delays and overdue-notice batching.',
            'pattern_label': 'mixed_pattern',
            'retrieval_context': 'Cross-thread reservation ordering lesson about duplicate holds after catalog sync delays.',
        }
    if has_reservation:
        return {
            'summary': 'Catalog sync delays previously caused duplicate holds because arrival-time ordering applied stale hold updates; item event time ordering was adopted to prevent duplicate holds.',
            'pattern_label': 'reservation_ordering_pattern',
            'retrieval_context': 'Cross-thread reservation ordering lesson about duplicate holds after catalog sync delays.',
        }
    if has_notification:
        return {
            'summary': 'Overdue notices are sent in 30-minute batches to avoid staff inbox spam.',
            'pattern_label': 'notification_batching_pattern',
            'retrieval_context': 'Carry-forward answer for overdue notice batching and staff inbox spam questions.',
        }
    return {
        'summary': 'A bounded pattern was recorded from prior conversation memory.',
        'pattern_label': 'generic_pattern',
        'retrieval_context': None,
    }


def _build_task_checkpoint_payload(user_prompt: str) -> dict[str, object]:
    lower = user_prompt.lower()
    inventory_batch = _build_inventory_batch_task_checkpoint_payload(lower)
    if inventory_batch is not None:
        return inventory_batch
    wallet_snapshot = _build_wallet_task_checkpoint_payload(lower)
    if wallet_snapshot is not None:
        return wallet_snapshot
    if 'retry window was exhausted' in lower and 'batch 418' in lower:
        return {
            'summary': 'Catalog sync retry resumed after auth refresh and is now blocked by a retry-window limit.',
            'task': 'Resume the catalog sync retry from the latest blocker state.',
            'current_state': 'The token is refreshed, the sync resumed from batch 313, and the latest blocker is a 429 after batch 417.',
            'key_findings': [
                'the service token is refreshed',
                'catalog API returned 429 because the retry window was exhausted',
            ],
            'blocker_state': 'Catalog API returned 429 because the retry window was exhausted after batch 417.',
            'next_step': 'Wait 15 minutes and resume from batch 418 with the refreshed token.',
            'evidence': [
                'Progress update: the service token is refreshed and the sync resumed from batch 313.',
                'Blocked: catalog API returned 429 after batch 417 because the retry window was exhausted.',
                'Next step: wait 15 minutes, resume from batch 418, and keep the refreshed token.',
            ],
            'freshness_signal': 'The current blocker is 429 after auth refresh; the older 401 is stale.',
        }
    if 'branch kiosk fallback' in lower and 're-request review' in lower:
        return {
            'summary': 'Ticket LIB-241 review is narrowed to the missing branch kiosk fallback before the next review pass.',
            'task': 'Resume the LIB-241 review follow-up.',
            'current_state': 'The admin toggle wiring is ready, but review is still blocked on branch kiosk fallback coverage.',
            'key_findings': [
                'keep the use_item_event_time flag off for branch kiosks until retry-path coverage exists',
                'branch kiosk fallback is still missing',
            ],
            'blocker_state': 'Review is blocked because the branch kiosk fallback is still missing.',
            'next_step': 'Add the branch kiosk fallback coverage and re-request review before enabling the flag.',
            'evidence': [
                'Decision: keep the use_item_event_time flag off for branch kiosks until retry-path coverage exists.',
                'Review progress: admin toggle wiring is ready, but the branch kiosk fallback is still missing.',
                'Next step: add the branch kiosk fallback coverage and re-request review before enabling the flag.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T12:02:00+00:00.',
        }
    if 'notify_digest_v2' in lower and 'scheduled-job backoff' in lower:
        return {
            'summary': 'Ticket LIB-314 is a different work item and still needs scheduled-job backoff before enablement.',
            'task': 'Resume ticket LIB-314 for the notification digest fix.',
            'current_state': 'The UI copy and migrations are done, and notify_digest_v2 remains gated.',
            'key_findings': [
                'keep the notification digest fix behind the notify_digest_v2 flag',
                'ticket LIB-314 has the UI copy and migrations done',
            ],
            'blocker_state': '',
            'next_step': 'Wire scheduled-job backoff before enabling notify_digest_v2.',
            'evidence': [
                'Decision: keep the notification digest fix behind the notify_digest_v2 flag.',
                'Partial progress: ticket LIB-314 has the UI copy and migrations done.',
                'Next step: wire scheduled-job backoff before enabling notify_digest_v2.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T15:32:00+00:00.',
        }
    if 'reservation cache is warm' in lower and 'compare cache invalidation' in lower:
        return {
            'summary': 'Duplicate-hold debugging is narrowed to warm-cache invalidation on delayed sync workers.',
            'task': 'Resume duplicate-hold debugging on delayed sync workers.',
            'current_state': 'Local replay confirmed the bug on delayed sync workers and narrowed the issue to cache invalidation with a warm reservation cache.',
            'key_findings': [
                'duplicate holds only reproduce on delayed sync workers when the reservation cache is warm',
                'local replay narrowed the issue to cache invalidation',
            ],
            'blocker_state': '',
            'next_step': 'Compare cache invalidation between delayed and immediate sync workers.',
            'evidence': [
                'Investigation found that duplicate holds only reproduce on delayed sync workers when the reservation cache is warm.',
                'Partial progress: local replay confirmed the bug and narrowed it to cache invalidation on delayed sync workers.',
                'Next step: compare cache invalidation between delayed and immediate sync workers.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T09:02:00+00:00.',
        }
    if 'service token expired' in lower and 'batch 313' in lower and 'admin portal' in lower and 'local browser' in lower:
        return {
            'summary': 'Catalog sync retry is blocked on an expired service token after partial progress through batch 312, and the operator must avoid admin portal sign-in or local browser use.',
            'task': 'Resume the catalog sync retry.',
            'current_state': '312 reservation records were refreshed before the retry failed with a 401 from the catalog API; continue without using the admin portal or a local browser.',
            'key_findings': [
                '312 reservation records were already refreshed',
                'the catalog API returned 401 because the service token expired',
                'avoid admin portal sign-in and local browser use during the retry',
            ],
            'blocker_state': 'Catalog API returned 401 because the service token expired; do not use admin portal sign-in or a local browser while resolving it.',
            'next_step': 'Refresh the catalog service token and rerun the sync from batch 313.',
            'evidence': [
                'Partial progress: refreshed 312 reservation records before the catalog sync tool failed.',
                'Blocked: catalog API returned 401 because the service token expired.',
                'Constraint: do not sign in to the admin portal or open a local browser.',
                'Next step: refresh the catalog service token and rerun the sync from batch 313.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00+00:00.',
            'retrieval_context': 'Catalog sync retry resume state anchored on the batch 313 restart after service-token failure.',
        }
    if 'service token expired' in lower and 'batch 313' in lower:
        return {
            'summary': 'Catalog sync retry is blocked on an expired service token after partial progress through batch 312.',
            'task': 'Resume the catalog sync retry.',
            'current_state': '312 reservation records were refreshed before the retry failed with a 401 from the catalog API.',
            'key_findings': [
                '312 reservation records were already refreshed',
                'the catalog API returned 401 because the service token expired',
            ],
            'blocker_state': 'Catalog API returned 401 because the service token expired.',
            'next_step': 'Refresh the catalog service token and rerun the sync from batch 313.',
            'evidence': [
                'Partial progress: refreshed 312 reservation records before the catalog sync tool failed.',
                'Blocked: catalog API returned 401 because the service token expired.',
                'Next step: refresh the catalog service token and rerun the sync from batch 313.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T10:02:00+00:00.',
            'retrieval_context': 'Catalog sync retry resume state anchored on the batch 313 restart after service-token failure.',
        }
    if 'schema change and backfill done' in lower and 'admin toggle' in lower:
        return {
            'summary': 'Ticket LIB-241 kept the reservation ordering fix behind the use_item_event_time flag and still needs enablement work.',
            'task': 'Resume ticket LIB-241 for the reservation ordering fix.',
            'current_state': 'The schema change and backfill are done, and the flag remains off pending the remaining enablement steps.',
            'key_findings': [
                'keep the reservation ordering fix behind the use_item_event_time flag',
                'ticket LIB-241 already has the schema change and backfill done',
            ],
            'blocker_state': '',
            'next_step': 'Wire the admin toggle and add retry-path coverage before enabling the flag.',
            'evidence': [
                'Decision: keep the reservation ordering fix behind the use_item_event_time flag.',
                'Partial progress: ticket LIB-241 has the schema change and backfill done.',
                'Next step: wire the admin toggle and add retry-path coverage before enabling the flag.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T11:02:00+00:00.',
            'retrieval_context': 'Flag-gated LIB-241 task state with remaining admin-toggle and retry-path coverage work.',
        }
    if 'arrival-time ordering' in lower and 'item event time' in lower:
        return {
            'summary': 'The delayed catalog sync investigation concluded that stale hold state under arrival-time ordering caused duplicate holds.',
            'task': 'Resume the delayed catalog sync investigation.',
            'current_state': 'The prior investigation and decision already identified the stale-state cause and the chosen fix.',
            'key_findings': [
                'arrival-time ordering reused stale hold state during delayed catalog sync',
                'item event time was chosen for reservation ordering',
            ],
            'blocker_state': '',
            'next_step': '',
            'evidence': [
                'Investigation found that arrival-time ordering reused stale hold state during delayed catalog sync and created duplicate holds.',
                'Decision: use item event time for reservation ordering to avoid duplicate holds after delayed catalog sync.',
            ],
            'freshness_signal': 'Latest explicit update at 2026-03-11T08:02:00+00:00.',
        }
    return {
        'summary': 'A compact task checkpoint was recorded for resumed work.',
        'task': 'Resume the previously recorded work item.',
        'current_state': 'Prior task state was recorded for later continuation.',
        'key_findings': ['Prior task context exists.'],
        'blocker_state': '',
        'next_step': '',
        'evidence': ['Prior task context exists.'],
        'freshness_signal': 'Latest explicit update time was not recorded.',
    }


def _build_continuity_payload(user_prompt: str) -> dict[str, str]:
    lower = user_prompt.lower()
    if '30-minute batches' in lower or 'staff inbox spam' in lower:
        return {
            'summary': 'The prior thread already answered why overdue notices are batched.',
            'continuity_question': 'Have we already answered why overdue notices are batched?',
            'carry_forward_answer': 'Yes. We previously decided to send overdue notices in 30-minute batches to avoid staff inbox spam.',
            'retrieval_context': 'Carry-forward answer for overdue notice batching and staff inbox spam questions.',
        }
    if any(term in lower for term in ('duplicate holds', 'arrival-time ordering', 'item event time')):
        return {
            'summary': 'The prior thread already answered the reservation-ordering follow-up.',
            'continuity_question': 'What did we previously conclude about duplicate holds after catalog sync delays?',
            'carry_forward_answer': 'We concluded that arrival-time ordering applied stale hold updates during catalog sync delays, so item event time ordering should carry forward to prevent duplicate holds.',
            'retrieval_context': 'Carry-forward answer for a repeated question from the same conversation thread.',
        }
    return {
        'summary': 'A prior thread already answered a repeated question.',
        'continuity_question': 'What prior answer should carry forward from this conversation thread?',
        'carry_forward_answer': 'A prior answer was already recorded in this conversation thread.',
        'retrieval_context': 'Carry-forward answer for a repeated question from the same conversation thread.',
    }


def _build_answer_payload(user_prompt: str) -> dict[str, object]:
    lower = user_prompt.lower()

    if 'what did we previously conclude about duplicate holds after catalog sync delays?' in lower:
        if 'memory/continuity_memory' in lower:
            return {
                'answer': 'We previously concluded that arrival-time ordering applied stale hold updates during catalog sync delays, so item event time ordering should carry forward to prevent duplicate holds.',
                'evidence_used': ['continuity_memory', 'arrival-time ordering applied stale hold updates', 'item event time ordering'],
            }
        if 'memory/pattern_memory' in lower and 'reservation_ordering_pattern' in lower:
            return {
                'answer': 'We previously concluded that catalog sync delays caused duplicate holds because arrival-time ordering applied stale hold updates, and we adopted item event time ordering to prevent duplicate holds.',
                'evidence_used': ['reservation_ordering_pattern', 'duplicate holds', 'item event time'],
            }
        if 'memory/decision' in lower or 'memory/investigation_outcome' in lower:
            return {
                'answer': 'We found that arrival-time ordering applied stale hold updates during catalog sync delays, and we chose item event time ordering to prevent duplicate holds.',
                'evidence_used': ['arrival-time ordering applied stale hold updates', 'use item event time for reservation ordering'],
            }
        return {
            'answer': 'The current thread says duplicate holds are happening again, but it does not include the earlier conclusion.',
            'evidence_used': [],
        }

    if 'from the duplicate-hold sync issue, what general lesson should we remember?' in lower:
        if 'memory/pattern_memory' in lower and 'reservation_ordering_pattern' in lower:
            return {
                'answer': 'The general lesson is that catalog sync delays can produce duplicate holds when arrival-time ordering applies stale updates, so item event time ordering is the safer pattern to carry forward.',
                'evidence_used': ['reservation_ordering_pattern', 'duplicate holds', 'item event time'],
            }
        if 'memory/decision' in lower or 'memory/investigation_outcome' in lower:
            return {
                'answer': 'We learned from the duplicate-hold issue that arrival-time ordering caused stale-update problems and item event time ordering fixed them.',
                'evidence_used': ['arrival-time ordering caused stale-update problems', 'item event time ordering fixed them'],
            }
        return {
            'answer': 'The current thread asks for a general lesson, but it does not include the earlier conclusion.',
            'evidence_used': [],
        }

    if 'have we already answered why overdue notices are batched?' in lower:
        if 'memory/continuity_memory' in lower:
            return {
                'answer': 'Yes. We already answered that overdue notices are sent in 30-minute batches to avoid staff inbox spam.',
                'evidence_used': ['continuity_memory', '30-minute batches', 'staff inbox spam'],
            }
        if 'memory/pattern_memory' in lower and 'notification_batching_pattern' in lower:
            return {
                'answer': 'Yes. Prior conversation memory already concluded that overdue notices should be sent in 30-minute batches to avoid staff inbox spam.',
                'evidence_used': ['notification_batching_pattern', '30-minute batches', 'staff inbox spam'],
            }
        if '30-minute batches' in lower:
            return {
                'answer': 'Yes. We previously decided to send overdue notices in 30-minute batches to avoid staff inbox spam.',
                'evidence_used': ['Decision: send overdue notices in 30-minute batches to avoid staff inbox spam.'],
            }
        return {
            'answer': 'The current thread says the question is being asked again, but it does not include the earlier answer.',
            'evidence_used': [],
        }

    if 'what answer should we carry forward for overdue notice batching?' in lower:
        if 'memory/continuity_memory' in lower:
            return {
                'answer': 'Carry forward the prior answer: overdue notices are sent in 30-minute batches to avoid staff inbox spam.',
                'evidence_used': ['continuity_memory', '30-minute batches', 'staff inbox spam'],
            }
        if 'memory/decision' in lower:
            return {
                'answer': 'The earlier answer was to send overdue notices in 30-minute batches to avoid staff inbox spam.',
                'evidence_used': ['Decision: send overdue notices in 30-minute batches to avoid staff inbox spam.'],
            }
        return {
            'answer': 'The current thread asks for a carry-forward answer, but it does not include the earlier conclusion.',
            'evidence_used': [],
        }

    if 'what ordering did we choose for reservation updates?' in lower:
        if 'memory/decision' in lower:
            return {
                'answer': 'We chose item event time for reservation ordering.',
                'evidence_used': ['use item event time for reservation ordering'],
            }
        if 'memory/continuity_memory' in lower:
            return {
                'answer': 'The prior thread says the ordering choice should carry forward, but it does not preserve the exact decision as directly as the lower-level record.',
                'evidence_used': ['continuity_memory'],
            }
        if 'memory/pattern_memory' in lower:
            return {
                'answer': 'We changed reservation ordering after sync-delay problems, using a safer ordering approach.',
                'evidence_used': ['reservation_ordering_pattern'],
            }
        return {
            'answer': 'The current thread does not contain the exact ordering choice.',
            'evidence_used': [],
        }

    if 'what exact batch interval did we choose for overdue notices?' in lower:
        if 'memory/decision' in lower:
            return {
                'answer': 'We chose 30-minute batches for overdue notices.',
                'evidence_used': ['30-minute batches'],
            }
        if 'memory/continuity_memory' in lower:
            return {
                'answer': 'The prior thread says batching should carry forward, but the exact interval is preserved more directly in the decision record.',
                'evidence_used': ['continuity_memory'],
            }
        if 'memory/pattern_memory' in lower:
            return {
                'answer': 'We chose batched overdue notices, but the exact interval is less direct in the higher-level pattern.',
                'evidence_used': ['notification_batching_pattern'],
            }
        return {
            'answer': 'The current thread does not include the exact batch interval.',
            'evidence_used': [],
        }

    if 'what exact finding supported the ordering change?' in lower:
        if 'source/assistant_artifact' in lower and 'arrival-time ordering applied stale hold updates' in lower:
            return {
                'answer': 'The exact finding was that arrival-time ordering applied stale hold updates during catalog sync delays.',
                'evidence_used': ['assistant_artifact source evidence', 'arrival-time ordering applied stale hold updates'],
            }
        if 'memory/investigation_outcome' in lower:
            return {
                'answer': 'The exact finding was that arrival-time ordering applied stale hold updates during catalog sync delays.',
                'evidence_used': ['arrival-time ordering applied stale hold updates'],
            }
        if 'memory/continuity_memory' in lower:
            return {
                'answer': 'The prior thread says there was an earlier answer about sync-delay hold problems, but the exact investigation finding still comes through more precisely from the lower-level record.',
                'evidence_used': ['continuity_memory'],
            }
        if 'memory/pattern_memory' in lower:
            return {
                'answer': 'The prior pattern says sync delays caused duplicate-hold problems, but it does not preserve the exact finding as clearly.',
                'evidence_used': ['reservation_ordering_pattern'],
            }
        return {
            'answer': 'The current thread does not include the exact investigation finding.',
            'evidence_used': [],
        }

    if 'which prior message backed the ordering change?' in lower:
        if 'source/assistant_artifact' in lower and 'arrival-time ordering applied stale hold updates' in lower:
            return {
                'answer': 'The prior supporting message was the investigation artifact stating that arrival-time ordering applied stale hold updates during catalog sync delays.',
                'evidence_used': ['assistant_artifact source evidence', 'arrival-time ordering applied stale hold updates'],
            }
        if 'memory/investigation_outcome' in lower:
            return {
                'answer': 'The investigation outcome said that arrival-time ordering applied stale hold updates during catalog sync delays.',
                'evidence_used': ['investigation_outcome'],
            }
        return {
            'answer': 'The current thread asks for a supporting message, but it does not include the earlier evidence.',
            'evidence_used': [],
        }

    if 'what was our verdict on the duplicate-hold sync problem?' in lower:
        if 'memory/investigation_outcome' in lower or 'memory/decision' in lower:
            return {
                'answer': 'Our verdict was that arrival-time ordering applied stale hold updates during catalog sync delays, so we switched to item event time ordering.',
                'evidence_used': ['arrival-time ordering applied stale hold updates', 'item event time ordering'],
            }
        if 'memory/thread_summary' in lower or 'memory/discussion_summary' in lower:
            return {
                'answer': 'The thread says the duplicate-hold issue was discussed and later fixed, but the sharp verdict is preserved more clearly in the investigation outcome and decision.',
                'evidence_used': ['thread summary'],
            }
        return {
            'answer': 'The visible context does not include the earlier duplicate-hold verdict.',
            'evidence_used': [],
        }

    if 'why is the rare-book reservation cutoff 48 hours?' in lower:
        return {
            'answer': 'The 48-hour cutoff reduces no-show holds before weekend pickups and gives the next patron time to collect the item.',
            'evidence_used': [],
        }

    if 'why do we use item event time for reservation ordering?' in lower:
        if 'memory/continuity_memory' in lower:
            return {
                'answer': 'We use item event time for reservation ordering because the earlier thread already concluded that arrival-time ordering caused sync-delay hold problems, and that answer should carry forward.',
                'evidence_used': ['continuity_memory', 'arrival-time ordering caused sync-delay hold problems'],
            }
        if 'memory/pattern_memory' in lower and 'reservation_ordering_pattern' in lower:
            return {
                'answer': 'We use item event time for reservation ordering because earlier catalog sync delays caused skipped or duplicate holds under arrival-time ordering, and the conversation pattern concluded that item event time ordering prevents that issue.',
                'evidence_used': ['reservation_ordering_pattern', 'catalog sync delays', 'skipped holds'],
            }
        if 'memory/decision' in lower or 'memory/investigation_outcome' in lower:
            return {
                'answer': 'We use item event time for reservation ordering because arrival-time ordering caused skipped holds during catalog sync delays.',
                'evidence_used': ['use item event time for reservation ordering', 'arrival-time ordering caused hold problems'],
            }
        return {
            'answer': 'We use item event time for reservation ordering.',
            'evidence_used': [],
        }

    return {
        'answer': 'The current thread context is sufficient for this question.',
        'evidence_used': [],
    }


def _extract_after_marker(text: str, marker: str) -> str:
    index = text.find(marker)
    if index == -1:
        return marker
    remainder = text[index + len(marker):].strip()
    sentence = remainder.split('\n', 1)[0].strip()
    return sentence.rstrip('.')


def _extract_sentence_containing(text: str, phrase: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if phrase in line:
            return line.rstrip('.')
    return phrase


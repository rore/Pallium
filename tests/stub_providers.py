from __future__ import annotations

import json

from providers.llm.base import LLMJsonResponse


class TieredMemorySemanticProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if 'pattern_label' in schema_description:
            payload = _build_pattern_payload(user_prompt)
        elif 'Thread items:' in user_prompt:
            payload = _build_thread_summary_payload(user_prompt)
        else:
            payload = _build_item_extraction_payload(user_prompt)
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


class TieredMemoryAnswerProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        payload = _build_answer_payload(user_prompt)
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _build_item_extraction_payload(user_prompt: str) -> dict[str, object]:
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
    if 'Investigation found' in user_prompt and 'Decision:' in user_prompt:
        return {
            'summary': 'The thread found that arrival-time ordering caused hold problems during catalog sync delays and decided to use item event time ordering.'
        }
    if 'Investigation found' in user_prompt:
        return {
            'summary': 'The thread found that arrival-time ordering caused hold problems during catalog sync delays.'
        }
    if '30-minute batches' in user_prompt:
        return {
            'summary': 'The thread decided to send overdue notices in 30-minute batches to avoid staff inbox spam.'
        }
    return {'summary': 'Unresolved.'}


def _build_pattern_payload(user_prompt: str) -> dict[str, str]:
    has_reservation = 'item event time' in user_prompt.lower() or 'arrival-time ordering' in user_prompt.lower()
    has_notification = '30-minute batches' in user_prompt.lower() or 'staff inbox spam' in user_prompt.lower()
    if has_reservation and has_notification:
        return {
            'summary': 'A mixed pattern mentions reservation ordering during sync delays and overdue-notice batching.',
            'pattern_label': 'mixed_pattern',
        }
    if has_reservation:
        return {
            'summary': 'Catalog sync delays previously caused reservation ordering problems; item event time ordering was adopted to prevent skipped or duplicate holds.',
            'pattern_label': 'reservation_ordering_pattern',
        }
    if has_notification:
        return {
            'summary': 'Overdue notices are sent in 30-minute batches to avoid staff inbox spam.',
            'pattern_label': 'notification_batching_pattern',
        }
    return {
        'summary': 'A bounded pattern was recorded from prior conversation memory.',
        'pattern_label': 'generic_pattern',
    }


def _build_answer_payload(user_prompt: str) -> dict[str, object]:
    lower = user_prompt.lower()
    if 'why do we use item event time for reservation ordering?' in lower:
        if 'memory/pattern_memory' in lower and 'reservation ordering problems' in lower:
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

    if 'have we already answered why overdue notices are batched?' in lower:
        if 'memory/pattern_memory' in lower and '30-minute batches' in lower:
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
            'answer': 'Yes, we already answered that overdue notices are batched.',
            'evidence_used': [],
        }

    return {
        'answer': 'The 48-hour cutoff reduces no-show holds before weekend pickups and gives the next patron time to collect the item.',
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



from __future__ import annotations

import json

from providers.llm.base import LLMJsonResponse


class TieredMemorySemanticProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if 'carry_forward_answer' in schema_description:
            payload = _build_continuity_payload(user_prompt)
        elif 'pattern_label' in schema_description:
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
    has_reservation = any(term in user_prompt.lower() for term in ('item event time', 'arrival-time ordering', 'duplicate holds', 'stale hold updates'))
    has_notification = '30-minute batches' in user_prompt.lower() or 'staff inbox spam' in user_prompt.lower()
    if has_reservation and has_notification:
        return {
            'summary': 'A mixed pattern mentions reservation ordering during sync delays and overdue-notice batching.',
            'pattern_label': 'mixed_pattern',
        }
    if has_reservation:
        return {
            'summary': 'Catalog sync delays previously caused duplicate holds because arrival-time ordering applied stale hold updates; item event time ordering was adopted to prevent duplicate holds.',
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


def _build_continuity_payload(user_prompt: str) -> dict[str, str]:
    lower = user_prompt.lower()
    if '30-minute batches' in lower or 'staff inbox spam' in lower:
        return {
            'summary': 'The prior thread already answered why overdue notices are batched.',
            'continuity_question': 'Have we already answered why overdue notices are batched?',
            'carry_forward_answer': 'Yes. We previously decided to send overdue notices in 30-minute batches to avoid staff inbox spam.',
        }
    if any(term in lower for term in ('duplicate holds', 'arrival-time ordering', 'item event time')):
        return {
            'summary': 'The prior thread already answered the reservation-ordering follow-up.',
            'continuity_question': 'What did we previously conclude about duplicate holds after catalog sync delays?',
            'carry_forward_answer': 'We concluded that arrival-time ordering applied stale hold updates during catalog sync delays, so item event time ordering should carry forward to prevent duplicate holds.',
        }
    return {
        'summary': 'A prior thread already answered a repeated question.',
        'continuity_question': 'What prior answer should carry forward from this conversation thread?',
        'carry_forward_answer': 'A prior answer was already recorded in this conversation thread.',
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

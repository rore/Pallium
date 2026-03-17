from __future__ import annotations

import json

from providers.llm.base import LLMJsonResponse
from tests.tiered_memory_stub_providers import _extract_after_marker, _extract_sentence_containing

class PublicCorpusSemanticProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        if 'freshness_signal' in schema_description:
            payload = _build_public_corpus_task_checkpoint_payload(user_prompt)
        elif 'carry_forward_answer' in schema_description:
            payload = _build_public_corpus_continuity_payload(user_prompt)
        elif 'pattern_label' in schema_description:
            payload = _build_public_corpus_pattern_payload(user_prompt)
        elif 'Thread items:' in user_prompt:
            payload = _build_public_corpus_thread_summary_payload(user_prompt)
        else:
            payload = _build_public_corpus_item_extraction_payload(user_prompt)
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


class PublicCorpusAnswerProvider:
    def generate_json(self, *, system_prompt: str, user_prompt: str, schema_description: str) -> LLMJsonResponse:
        payload = _build_public_corpus_answer_payload(user_prompt)
        return LLMJsonResponse(raw_text=json.dumps(payload), parsed_json=payload)


def _build_public_corpus_item_extraction_payload(user_prompt: str) -> dict[str, object]:
    if 'Decision:' in user_prompt:
        decision_text = _extract_after_marker(user_prompt, 'Decision:')
        rationale_text = None
        for split_marker in (' so ', ' to '):
            if split_marker in decision_text:
                prefix, suffix = decision_text.split(split_marker, 1)
                decision_text = prefix.strip()
                rationale_text = f"{split_marker.strip()} {suffix.strip()}"
                break
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


def _build_public_corpus_thread_summary_payload(user_prompt: str) -> dict[str, str]:
    lower = user_prompt.lower()
    if '1:2:2 starter feed' in lower and 'cold storage slows recovery' in lower:
        return {
            'summary': 'The thread chose a 1:2:2 starter feed and explained that cold storage slows recovery.'
        }
    if 'done / waiting / next owner' in lower:
        return {
            'summary': "The thread chose the 'Done / Waiting / Next owner' handoff template for short updates."
        }
    if 'branch kiosk fallback coverage is still missing' in lower and 'kiosk smoke tests' in lower:
        return {
            'summary': 'The thread finished the approval step, but branch kiosk fallback coverage is still missing and the next step is to rerun kiosk smoke tests after fixing it.'
        }
    if 'backtracking' in lower and 'store section' in lower:
        return {
            'summary': 'The thread found that unordered grocery lists cause backtracking and chose store-section grouping.'
        }
    if '1gi' in lower and '512mi' in lower:
        return {
            'summary': 'The thread found that the export worker hit the 512Mi memory limit and decided to raise the limit to 1Gi.'
        }
    if 'retry window was exhausted' in lower and 'batch 418' in lower:
        return {
            'summary': 'The thread resumed the sync after auth refresh and the latest blocker is a retry-window 429, with the next step to resume from batch 418.'
        }
    if 'problem framing' in lower and 'tradeoffs' in lower and 'ownership' in lower:
        return {
            'summary': 'The thread chose the three-bucket interview rubric: problem framing, tradeoffs, and ownership.'
        }
    if 'job already running, skipping new start' in lower:
        return {
            'summary': "The thread found that overlapping retries were proven by the log line 'job already running, skipping new start'."
        }
    return {'summary': 'Unresolved.'}


def _build_public_corpus_pattern_payload(user_prompt: str) -> dict[str, str]:
    lower = user_prompt.lower()
    if 'backtracking' in lower and ('store section' in lower or 'produce, dairy, pantry, and freezer' in lower):
        return {
            'summary': 'Across the grocery-planning chats, the recurring problem was store backtracking from unordered lists, and the recurring fix was grouping the list by store section before shopping.',
            'pattern_label': 'grocery_backtracking_pattern',
        }
    return {
        'summary': 'A bounded pattern was recorded from prior conversation memory.',
        'pattern_label': 'generic_pattern',
    }


def _build_public_corpus_task_checkpoint_payload(user_prompt: str) -> dict[str, object]:
    lower = user_prompt.lower()
    if 'branch kiosk fallback coverage is still missing' in lower and 'kiosk smoke tests' in lower:
        return {
            'summary': 'The branch kiosk handoff cleanup is still blocked on fallback coverage.',
            'task': 'Resume the branch kiosk handoff cleanup.',
            'current_state': 'VPN approval is already done, and the remaining blocker is branch kiosk fallback coverage.',
            'key_findings': ['VPN approval is done.', 'Branch kiosk fallback coverage is still missing.'],
            'blocker_state': 'Branch kiosk fallback coverage is still missing before the rollout can continue.',
            'next_step': 'Add the branch kiosk fallback note and rerun kiosk smoke tests.',
            'evidence': [
                'Partial progress: VPN approval is done and the rollout note is updated.',
                'Blocked: branch kiosk fallback coverage is still missing before the rollout can continue.',
                'Next step: add the branch kiosk fallback note and rerun kiosk smoke tests.',
            ],
            'freshness_signal': 'The latest blocker is branch kiosk fallback coverage; the older VPN-approval blocker is stale.',
        }
    if 'retry window was exhausted' in lower and 'batch 418' in lower:
        return {
            'summary': 'The catalog sync retry is now blocked by a retry-window limit after auth recovery.',
            'task': 'Resume the catalog sync retry from the latest blocker state.',
            'current_state': 'The token refresh worked, the sync resumed through batch 417, and the current blocker is a 429 retry-window limit.',
            'key_findings': ['The sync resumed from batch 313 and reached batch 417.', 'The retry window is exhausted.'],
            'blocker_state': 'Catalog API returned 429 because the retry window was exhausted.',
            'next_step': 'Wait 15 minutes and resume from batch 418.',
            'evidence': [
                'Partial progress: the sync resumed from batch 313 and reached batch 417.',
                'Blocked: catalog API returned 429 because the retry window was exhausted.',
                'Next step: wait 15 minutes and resume from batch 418.',
            ],
            'freshness_signal': 'The latest blocker is the retry-window 429; the older expired-token blocker is stale.',
        }
    if 'done / waiting / next owner' in lower:
        return {
            'summary': 'The handoff template choice should carry forward for resumed work.',
            'task': 'Reuse the short handoff template.',
            'current_state': 'A concise three-line template was already chosen for follow-up updates.',
            'key_findings': ["Use the three-line handoff template 'Done / Waiting / Next owner'."],
            'blocker_state': '',
            'next_step': 'Use the same three-line template in the next handoff.',
            'evidence': ["The thread chose the 'Done / Waiting / Next owner' handoff template for short updates."],
            'freshness_signal': 'Latest explicit update time was not recorded.',
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


def _build_public_corpus_continuity_payload(user_prompt: str) -> dict[str, str]:
    lower = user_prompt.lower()
    if 'done / waiting / next owner' in lower:
        return {
            'summary': 'The prior thread already answered which handoff template to use.',
            'continuity_question': 'Have we already answered what short handoff template to use?',
            'carry_forward_answer': "Yes. Use the three-line handoff template 'Done / Waiting / Next owner'.",
        }
    return {
        'summary': 'A prior thread already answered a repeated question.',
        'continuity_question': 'What prior answer should carry forward?',
        'carry_forward_answer': 'A prior answer should carry forward from the earlier thread.',
    }


def _build_public_corpus_answer_payload(user_prompt: str) -> dict[str, object]:
    lower = user_prompt.lower()

    if 'what exact feed ratio did you tell me to use again?' in lower:
        if 'memory/decision' in lower or 'source/assistant_artifact' in lower or 'source/public_corpus_turn' in lower:
            return {
                'answer': 'Use a 1:2:2 starter feed so the acidity drops faster.',
                'evidence_used': ['1:2:2 starter feed', 'acidity drops'],
            }
        return {
            'answer': 'The current question asks for the exact starter ratio again, but the visible context does not include it.',
            'evidence_used': [],
        }

    if 'which earlier note explained why keeping it cold was a bad idea?' in lower or ('what evidence showed' in lower and 'cold storage slows recovery' in lower):
        if 'cold storage slows recovery' in lower:
            return {
                'answer': 'The earlier note said cold storage slows recovery and keeps the sour smell around longer.',
                'evidence_used': ['cold storage slows recovery', 'sour smell'],
            }
        return {
            'answer': 'The visible context does not include the earlier recovery evidence.',
            'evidence_used': [],
        }

    if 'can you paste that gentle rewrite again exactly?' in lower:
        if 'i missed your call earlier and wanted to apologize for going quiet.' in lower:
            return {
                'answer': 'Sure: "I missed your call earlier and wanted to apologize for going quiet. Can we try again later today?"',
                'evidence_used': ['gentle rewrite', 'missed your call'],
            }
        return {
            'answer': 'The visible context does not include the rewrite.',
            'evidence_used': [],
        }

    if 'have we already answered what short handoff template to use?' in lower or 'old handoff template answer' in lower:
        if 'memory/continuity_memory' in lower:
            return {
                'answer': "Yes. Use the three-line handoff template 'Done / Waiting / Next owner'.",
                'evidence_used': ['continuity_memory', 'Done / Waiting / Next owner'],
            }
        if 'memory/decision' in lower:
            return {
                'answer': "We previously said to use the three-line handoff template 'Done / Waiting / Next owner'.",
                'evidence_used': ['Done / Waiting / Next owner'],
            }
        return {
            'answer': 'The visible context does not show the earlier handoff-template answer.',
            'evidence_used': [],
        }
    if ('what blocker is still live' in lower and 'what should i do next' in lower) or ('what blocker remained' in lower and 'what should happen next' in lower) or 'blocker and next step are already visible in this thread' in lower:
        if ('branch kiosk fallback coverage is still missing' in lower and 'kiosk smoke tests' in lower) or ('memory/task_checkpoint' in lower and 'branch kiosk' in lower):
            return {
                'answer': 'The current blocker is that branch kiosk fallback coverage is still missing, and the next step is to add the branch kiosk fallback note and rerun kiosk smoke tests.',
                'evidence_used': ['branch kiosk fallback coverage is still missing', 'kiosk smoke tests'],
            }
        return {
            'answer': 'The visible context does not include the latest branch-kiosk blocker state.',
            'evidence_used': [],
        }

    if 'what did we previously conclude about why grocery trips keep dragging out?' in lower or 'big picture on why grocery trips keep dragging out' in lower:
        if 'memory/pattern_memory' in lower and 'backtracking' in lower and 'store section' in lower:
            return {
                'answer': 'We previously concluded that the trips drag out because unordered lists cause repeated backtracking, so the fix is to group the list by store section before shopping.',
                'evidence_used': ['pattern_memory', 'backtracking', 'store section'],
            }
        if 'memory/decision' in lower or 'memory/investigation_outcome' in lower:
            return {
                'answer': 'We found that unordered lists caused backtracking and suggested grouping the list before shopping.',
                'evidence_used': ['backtracking', 'group the list before shopping'],
            }
        return {
            'answer': 'The visible context does not include the earlier grocery-planning conclusion.',
            'evidence_used': [],
        }

    if 'what resource cap did you say to bump for the export worker again?' in lower or ('memory limit' in lower and '512mi' in lower) or ('memory cap' in lower and 'request stays' in lower):
        if ('memory/decision' in lower or 'source/public_corpus_turn' in lower) and '1gi' in lower:
            return {
                'answer': 'Raise the worker memory limit to 1Gi while keeping the request at 512Mi.',
                'evidence_used': ['1Gi', '512Mi'],
            }
        return {
            'answer': 'The visible context does not include the earlier export-worker resource recommendation.',
            'evidence_used': [],
        }

    if 'can you rewrite that as short bullets for a text message?' in lower:
        if 'fushimi inari' in lower and 'arashiyama' in lower:
            return {
                'answer': '- Day 1: Fushimi Inari and Gion\n- Day 2: Arashiyama and Kinkaku-ji\n- Day 3: Nishiki Market and Pontocho',
                'evidence_used': ['Fushimi Inari', 'Arashiyama', 'bullet'],
            }
        return {
            'answer': 'The visible context does not include the itinerary to rewrite.',
            'evidence_used': [],
        }

    if 'remind me of those buckets again.' in lower:
        if ('memory/decision' in lower or 'source/public_corpus_turn' in lower) and 'problem framing' in lower and 'tradeoffs' in lower and 'ownership' in lower:
            return {
                'answer': 'Use the three headings problem framing, tradeoffs, and ownership.',
                'evidence_used': ['problem framing', 'tradeoffs', 'ownership'],
            }
        return {
            'answer': 'The visible context does not include the earlier scorecard headings.',
            'evidence_used': [],
        }

    if 'which exact log line proved the retries were overlapping?' in lower or 'paste the overlap-proof line again for the incident note' in lower or 'which exact overlap-proof line should i paste into the incident note?' in lower:
        if 'job already running, skipping new start' in lower:
            return {
                'answer': "The exact log line was 'job already running, skipping new start'.",
                'evidence_used': ['job already running, skipping new start'],
            }
        return {
            'answer': 'The visible context does not include the earlier log evidence.',
            'evidence_used': [],
        }
    if ('what is the current blocker' in lower and 'what should i do next' in lower) or ('what is the live blocker' in lower and 'resume point now' in lower) or ('what blocker did we hit now' in lower and 'where do i resume from' in lower) or 'current blocker and resume point are already visible in this thread' in lower:
        if ('retry window was exhausted' in lower and 'batch 418' in lower) or ('memory/task_checkpoint' in lower and 'catalog sync retry' in lower):
            return {
                'answer': 'The current blocker is a 429 because the retry window was exhausted, and the next step is to wait 15 minutes and resume from batch 418.',
                'evidence_used': ['retry window was exhausted', 'batch 418'],
            }
        return {
            'answer': 'The visible context does not include the latest sync-retry blocker state.',
            'evidence_used': [],
        }

    return {
        'answer': 'The current thread context is sufficient for this question.',
        'evidence_used': [],
    }










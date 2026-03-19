from __future__ import annotations

import argparse
import json
import shlex
from dataclasses import dataclass
from typing import Any, Callable

from app.agent_simulation_http import HarnessHttpClient, HarnessHttpError
from app.agent_simulation_model import ModelUnavailableError, ThinAgentModel
from app.agent_simulation_render import render_debug_summary, render_replay_diff, render_scope
from app.agent_simulation_session import (
    HarnessSession,
    SessionStore,
    create_default_session,
    new_ref,
    rewrite_payload_for_replay,
    rewrite_session_for_replay,
)

from providers.llm.base import LLMProviderError


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TURN_KINDS = {"new_thread", "same_thread", "same_thread_continuation", "resumed_session", "new_session"}
ARTIFACT_KINDS = {"tool_use_summary", "todo_snapshot"}
PROMPT_ACTIONS = {"a": "accepted", "e": "edited", "d": "discarded"}
CHAT_MODES = {"chat", "chat-lite"}


@dataclass
class TerminalIO:
    input_func: Callable[[str], str] = input
    output_func: Callable[[str], None] = print
    prompt_formatter: Callable[[str], str] | None = None
    output_formatter: Callable[[str, str], str] | None = None

    def prompt(self, text: str) -> str:
        rendered = self.prompt_formatter(text) if self.prompt_formatter is not None else text
        return self.input_func(rendered)

    def write(self, text: str) -> None:
        self.output_func(text)

    def write_role(self, role: str, text: str) -> None:
        rendered = self.output_formatter(role, text) if self.output_formatter is not None else text
        self.output_func(rendered)


class AgentSimulationApp:
    def __init__(
        self,
        *,
        http_client: HarnessHttpClient,
        io: TerminalIO | None = None,
        session_store: SessionStore | None = None,
        model: ThinAgentModel | None = None,
        ref_factory: Callable[[str], str] = new_ref,
    ) -> None:
        self._http = http_client
        self._io = io or TerminalIO()
        self._store = session_store or SessionStore()
        self._model = model or ThinAgentModel()
        self._ref_factory = ref_factory
        self._session = create_default_session(base_url=http_client.base_url, mode="chat", model=self._model.resolution().to_dict())
        self._mode = "chat"

    @property
    def session(self) -> HarnessSession:
        return self._session

    def run(self, *, mode: str, replay_path: str | None = None) -> int:
        self._mode = mode
        self._session.set_mode(mode)
        if mode == "replay":
            if not replay_path:
                replay_path = self._io.prompt("Replay session path: ").strip()
            if not replay_path:
                self._write_error("Replay path required")
                return 1
            self._run_replay(replay_path)
            return 0

        self._write_scope()
        while True:
            try:
                line = self._io.prompt(f"{self._mode}> ").strip()
                if not line:
                    continue
                if line.startswith("/"):
                    if not self._handle_command(line):
                        return 0
                    continue
                if self._mode in CHAT_MODES:
                    self.process_chat_message(line)
                else:
                    self._write_system("manual mode accepts slash commands only")
            except ValueError as exc:
                self._write_error(str(exc))

    def process_chat_message(self, message: str) -> None:
        user_request = self._build_item_payload(
            source_type="chat_message",
            artifact_kind="message",
            role="user",
            content=message,
        )
        user_response = self._http.create_item(user_request)
        query_request = self._build_query_payload(message)
        query_response = self._http.query_debug(query_request)
        if self._mode != "chat-lite" or self._session.debug_enabled:
            self._write_debug_lines(render_debug_summary(query_response, verbose=self._session.debug_enabled))

        event: dict[str, Any] = {
            "event_type": "chat_turn",
            "mode": self._mode,
            "scope": self._scope_snapshot(),
            "user_message": message,
            "user_item": {"request": user_request, "response": user_response},
            "query_debug": {"request": query_request, "response": query_response},
        }

        assistant_result = self._draft_or_fallback(message, query_response)
        event["model"] = assistant_result["model"]
        event["operator_action"] = assistant_result["operator_action"]
        if assistant_result.get("assistant"):
            assistant = assistant_result["assistant"]
            event["assistant"] = assistant
        if assistant_result.get("artifact"):
            event["artifact"] = assistant_result["artifact"]

        self._session.record_event(event)

    def execute_manual_query(self, text: str, *, debug: bool) -> dict[str, Any]:
        request = self._build_query_payload(text)
        response = self._http.query_debug(request) if debug else self._http.query(request)
        event_type = "manual_query_debug" if debug else "manual_query"
        self._session.record_event(
            {
                "event_type": event_type,
                "scope": self._scope_snapshot(),
                "request": request,
                "response": response,
            }
        )
        if debug:
            self._write_debug_lines(render_debug_summary(response, verbose=self._session.debug_enabled))
        else:
            for line in json.dumps(response, indent=2).splitlines():
                self._write_system(line)
        return response

    def execute_manual_item(self) -> dict[str, Any]:
        source_type = self._prompt_required("source_type: ")
        content = self._prompt_required("content: ")
        artifact_kind = self._prompt_optional("artifact_kind [message|assistant_output|tool_use_summary|todo_snapshot]: ") or None
        role = self._prompt_optional("role [user|assistant]: ") or None
        source_id = self._prompt_optional("source_id [auto]: ") or self._ref_factory("manual-item")
        payload = self._build_item_payload(
            source_type=source_type,
            artifact_kind=artifact_kind,
            role=role,
            content=content,
            source_id=source_id,
        )
        response = self._http.create_item(payload)
        self._session.record_event(
            {
                "event_type": "manual_item",
                "scope": self._scope_snapshot(),
                "request": payload,
                "response": response,
            }
        )
        self._write_system(json.dumps(response, indent=2))
        return response

    def _handle_command(self, line: str) -> bool:
        parts = shlex.split(line)
        command = parts[0].lower()
        args = parts[1:]
        if command in {"/quit", "/exit"}:
            return False
        if command == "/help":
            self._write_help()
            return True
        if command == "/scope":
            if args and args[0] == "show":
                self._write_scope()
            else:
                self._prompt_scope_update()
            return True
        if command == "/show" and args == ["scope"]:
            self._write_scope()
            return True
        if command == "/turn":
            self._set_turn_kind(args[0] if args else None)
            return True
        if command == "/local-context":
            self._set_local_context(args[0] if args else None)
            return True
        if command == "/debug":
            self._set_debug(args[0] if args else None)
            return True
        if command == "/fork":
            self._fork_scope(new_session="--new-session" in args)
            return True
        if command in {"/save", "/export"}:
            self._save_session(args[0] if args else None)
            return True
        if command == "/replay":
            path = args[0] if args else self._io.prompt("Replay session path: ").strip()
            if path:
                self._run_replay(path)
            return True
        if command == "/mode":
            self._set_mode(args[0] if args else None)
            return True
        if command == "/artifact":
            artifact = self._prompt_for_artifact()
            if artifact is not None:
                self._session.record_event({"event_type": "manual_artifact", "scope": self._scope_snapshot(), "artifact": artifact})
            return True
        if command == "/items":
            self.execute_manual_item()
            return True
        if command == "/query":
            text = " ".join(args).strip()
            if not text:
                text = self._prompt_required("query text: ")
            self.execute_manual_query(text, debug=False)
            return True
        if command == "/query-debug":
            text = " ".join(args).strip()
            if not text:
                text = self._prompt_required("query text: ")
            self.execute_manual_query(text, debug=True)
            return True
        self._write_warning(f"Unknown command: {command}")
        return True

    def _draft_or_fallback(self, message: str, query_response: dict[str, Any]) -> dict[str, Any]:
        injectable_blocks = query_response.get("injectable_blocks") if query_response.get("should_inject") else []
        try:
            draft = self._model.draft_answer(user_message=message, injectable_blocks=injectable_blocks or [])
        except (ModelUnavailableError, LLMProviderError) as exc:
            return self._manual_fallback(str(exc))

        result: dict[str, Any] = {
            "model": {
                "origin": "model",
                "resolution": draft.resolution.to_dict(),
                "request": draft.model_request,
                "response": draft.model_response,
            },
        }
        if self._mode == "chat-lite":
            self._write_agent(draft.answer)
            assistant = self._ingest_assistant(draft.answer, origin="model")
            result["assistant"] = assistant
            result["operator_action"] = "auto_accepted"
            return result

        self._write_system("assistant draft:")
        self._write_agent(draft.answer)
        action = self._prompt_action()
        result["operator_action"] = action
        if action == "discarded":
            return result
        answer_text = draft.answer
        if action == "edited":
            answer_text = self._prompt_required_retry("edited assistant reply: ")
        assistant = self._ingest_assistant(answer_text, origin="model")
        result["assistant"] = assistant
        artifact = self._prompt_artifact_after_turn()
        if artifact is not None:
            result["artifact"] = artifact
        return result

    def _manual_fallback(self, reason: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "model": {
                "origin": "manual_fallback",
                "resolution": self._model.resolution().to_dict(),
                "failure_reason": reason,
            },
            "operator_action": "manual_discarded",
        }
        if self._mode == "chat-lite":
            self._write_warning(f"Model unavailable: {reason}")
            result["operator_action"] = "auto_skipped"
            return result

        self._write_warning(f"Model unavailable; enter assistant reply manually or leave blank to discard. Reason: {reason}")
        manual_text = self._io.prompt("assistant> ").strip()
        if not manual_text:
            return result
        assistant = self._ingest_assistant(manual_text, origin="manual_fallback")
        result["assistant"] = assistant
        result["operator_action"] = "manual_entry"
        artifact = self._prompt_artifact_after_turn()
        if artifact is not None:
            result["artifact"] = artifact
        return result

    def _ingest_assistant(self, text: str, *, origin: str) -> dict[str, Any]:
        payload = self._build_item_payload(
            source_type="assistant_artifact",
            artifact_kind="assistant_output",
            role="assistant",
            content=text,
        )
        response = self._http.create_item(payload)
        return {
            "origin": origin,
            "content": text,
            "request": payload,
            "response": response,
        }

    def _prompt_artifact_after_turn(self) -> dict[str, Any] | None:
        choice = self._io.prompt("Add artifact now? [y/N]: ").strip().lower()
        if choice not in {"y", "yes"}:
            return None
        return self._prompt_for_artifact()

    def _prompt_for_artifact(self) -> dict[str, Any] | None:
        kind = self._prompt_optional("artifact kind [tool_use_summary|todo_snapshot]: ").strip() or "tool_use_summary"
        if kind not in ARTIFACT_KINDS:
            self._write_warning(f"Unsupported artifact kind: {kind}")
            return None
        content = self._prompt_required_retry("artifact text: ")
        payload = self._build_item_payload(
            source_type="assistant_artifact",
            artifact_kind=kind,
            role="assistant",
            content=content,
        )
        response = self._http.create_item(payload)
        self._write_system(f"artifact stored: {response.get('source_item_id')}")
        return {
            "kind": kind,
            "content": content,
            "request": payload,
            "response": response,
        }

    def _build_item_payload(
        self,
        *,
        source_type: str,
        artifact_kind: str | None,
        role: str | None,
        content: str,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "source_type": source_type,
            "source_id": source_id or self._ref_factory(source_type),
            "content_type": "text/plain",
            "content": content,
            "artifact_kind": artifact_kind,
            "role": role,
            "container_ref": self._session.defaults.container_ref,
            "thread_ref": self._session.defaults.thread_ref,
            "session_ref": self._session.defaults.session_ref,
            "visibility_context": self._session.defaults.visibility_context,
        }
        return {key: value for key, value in payload.items() if value is not None}

    def _build_query_payload(self, text: str) -> dict[str, Any]:
        payload = {
            "text": text,
            "limit": 5,
            "container_ref": self._session.defaults.container_ref,
            "thread_ref": self._session.defaults.thread_ref,
            "session_ref": self._session.defaults.session_ref,
            "visibility_context": self._session.defaults.visibility_context,
        }
        runtime_context = self._runtime_context_payload()
        if runtime_context is not None:
            payload["runtime_context"] = runtime_context
        return {key: value for key, value in payload.items() if value is not None}

    def _runtime_context_payload(self) -> dict[str, Any] | None:
        runtime = self._session.defaults.runtime_context
        turn_kind = runtime.get("turn_kind")
        local_context = runtime.get("session_has_sufficient_local_context")
        if turn_kind is None and local_context is None:
            return None
        return {
            "turn_kind": turn_kind,
            "session_has_sufficient_local_context": local_context,
        }

    def _prompt_action(self) -> str:
        raw = self._io.prompt("accept/edit/discard [a/e/d]: ").strip().lower()
        return PROMPT_ACTIONS.get(raw, "discarded")

    def _write_scope(self) -> None:
        for line in render_scope(self._scope_snapshot()):
            self._write_system(line)

    def _scope_snapshot(self) -> dict[str, Any]:
        return self._session.defaults.to_dict()

    def _prompt_scope_update(self) -> None:
        defaults = self._session.defaults
        container_ref = self._prompt_optional(f"container_ref [{defaults.container_ref}]: ") or defaults.container_ref
        thread_ref = self._prompt_optional(f"thread_ref [{defaults.thread_ref}]: ") or defaults.thread_ref
        session_ref = self._prompt_optional(f"session_ref [{defaults.session_ref}]: ") or defaults.session_ref
        current_visibility = defaults.visibility_context or {"kind": "public", "id": None}
        visibility_kind = self._prompt_optional(f"visibility kind [{current_visibility.get('kind')}]: ") or current_visibility.get("kind")
        visibility_id = current_visibility.get("id")
        if visibility_kind == "public":
            visibility_id = None
        else:
            visibility_id = self._prompt_optional(f"visibility id [{visibility_id}]: ") or visibility_id
        defaults.container_ref = container_ref
        defaults.thread_ref = thread_ref
        defaults.session_ref = session_ref
        defaults.visibility_context = {"kind": visibility_kind, "id": visibility_id}
        self._write_scope()

    def _set_turn_kind(self, value: str | None) -> None:
        if value is None:
            value = self._prompt_optional("turn kind [new_thread|same_thread|same_thread_continuation|resumed_session|new_session|clear]: ")
        if not value:
            self._write_system(f"turn_kind: {self._session.defaults.runtime_context.get('turn_kind')}")
            return
        if value == "clear":
            self._session.defaults.runtime_context["turn_kind"] = None
        elif value in TURN_KINDS:
            self._session.defaults.runtime_context["turn_kind"] = value
        else:
            self._write_warning(f"Unsupported turn kind: {value}")
            return
        self._write_system(f"turn_kind set to {self._session.defaults.runtime_context.get('turn_kind')}")

    def _set_local_context(self, value: str | None) -> None:
        if value is None:
            value = self._prompt_optional("local context [true|false|clear]: ")
        if not value:
            self._write_system(
                f"session_has_sufficient_local_context: {self._session.defaults.runtime_context.get('session_has_sufficient_local_context')}"
            )
            return
        lowered = value.lower()
        if lowered == "clear":
            parsed = None
        elif lowered in {"true", "yes", "y", "1"}:
            parsed = True
        elif lowered in {"false", "no", "n", "0"}:
            parsed = False
        else:
            self._write_warning(f"Unsupported local-context value: {value}")
            return
        self._session.defaults.runtime_context["session_has_sufficient_local_context"] = parsed
        self._write_system(f"session_has_sufficient_local_context set to {parsed}")

    def _set_debug(self, value: str | None) -> None:
        if value not in {"on", "off"}:
            value = self._prompt_optional("debug [on|off]: ") or value
        if value not in {"on", "off"}:
            self._write_system(f"debug: {'on' if self._session.debug_enabled else 'off'}")
            return
        self._session.debug_enabled = value == "on"
        self._write_system(f"debug set to {value}")

    def _fork_scope(self, *, new_session: bool) -> None:
        self._session.defaults.thread_ref = self._ref_factory("thread")
        if new_session:
            self._session.defaults.session_ref = self._ref_factory("session")
        self._session.defaults.runtime_context["turn_kind"] = "new_thread"
        self._write_scope()

    def _save_session(self, name: str | None) -> None:
        path = self._store.save(self._session, name=name)
        self._write_system(f"session saved to {path}")

    def _set_mode(self, mode: str | None) -> None:
        if mode not in {"chat", "chat-lite", "manual"}:
            mode = self._prompt_optional("mode [chat|chat-lite|manual]: ") or mode
        if mode not in {"chat", "chat-lite", "manual"}:
            self._write_system(f"current mode: {self._mode}")
            return
        self._mode = mode
        self._session.set_mode(mode)
        self._write_system(f"mode set to {mode}")

    def _run_replay(self, path: str) -> None:
        loaded = self._store.load(path)
        replay = rewrite_session_for_replay(loaded)
        self._write_system(f"replaying {path}")
        for event in loaded.events:
            self._replay_event(event, replay.session_id)

    def _replay_event(self, event: dict[str, Any], replay_id: str) -> None:
        event_type = event.get("event_type")
        if event_type == "chat_turn":
            user_item = rewrite_payload_for_replay(event["user_item"]["request"], replay_id)
            self._http.create_item(user_item)
            recorded_query = event["query_debug"]
            current_query = self._http.query_debug(rewrite_payload_for_replay(recorded_query["request"], replay_id))
            self._write_debug_lines(["replay diff:"])
            self._write_debug_lines(render_replay_diff(recorded_query["response"], current_query))
            assistant = event.get("assistant")
            if assistant is not None:
                self._http.create_item(rewrite_payload_for_replay(assistant["request"], replay_id))
            artifact = event.get("artifact")
            if artifact is not None:
                self._http.create_item(rewrite_payload_for_replay(artifact["request"], replay_id))
            return
        if event_type == "manual_query_debug":
            current = self._http.query_debug(rewrite_payload_for_replay(event["request"], replay_id))
            self._write_debug_lines(render_replay_diff(event["response"], current))
            return
        if event_type == "manual_query":
            current = self._http.query(rewrite_payload_for_replay(event["request"], replay_id))
            self._write_debug_lines(render_replay_diff(event["response"], current))
            return
        if event_type in {"manual_item", "manual_artifact"}:
            request = event.get("request") or (event.get("artifact") or {}).get("request")
            if request is not None:
                self._http.create_item(rewrite_payload_for_replay(request, replay_id))

    def _prompt_required(self, text: str) -> str:
        value = self._io.prompt(text).strip()
        if not value:
            raise ValueError(f"Required input missing for prompt: {text}")
        return value

    def _prompt_required_retry(self, text: str) -> str:
        while True:
            value = self._io.prompt(text).strip()
            if value:
                return value
            self._write_error(f"Required input missing for prompt: {text}")

    def _prompt_optional(self, text: str) -> str:
        return self._io.prompt(text).strip()

    def _write_help(self) -> None:
        for line in (
            "/scope",
            "/show scope",
            "/turn",
            "/local-context",
            "/artifact",
            "/fork [--new-session]",
            "/debug on|off",
            "/save [name]",
            "/export [name]",
            "/replay [path]",
            "/mode chat|chat-lite|manual",
            "/items",
            "/query <text>",
            "/query-debug <text>",
            "/quit",
        ):
            self._write_system(line)

    def _write_agent(self, text: str) -> None:
        self._io.write_role("agent", text)

    def _write_system(self, text: str) -> None:
        self._io.write_role("system", text)

    def _write_warning(self, text: str) -> None:
        self._io.write_role("warning", text)

    def _write_error(self, text: str) -> None:
        self._io.write_role("error", text)

    def _write_debug_lines(self, lines: list[str]) -> None:
        for line in lines:
            self._io.write_role("debug", line)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Pallium direct thin-agent simulation harness")
    parser.add_argument("mode", nargs="?", choices=("chat", "chat-lite", "manual", "replay"), default="chat")
    parser.add_argument("session_path", nargs="?")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    return parser


def run(args: list[str] | None = None) -> int:
    parsed = build_parser().parse_args(args)
    http_client = HarnessHttpClient(base_url=parsed.base_url)
    model = ThinAgentModel(provider_override=parsed.provider, model_override=parsed.model)
    from app.agent_simulation_terminal import build_terminal_io

    app = AgentSimulationApp(http_client=http_client, model=model, io=build_terminal_io())
    try:
        return app.run(mode=parsed.mode, replay_path=parsed.session_path)
    except HarnessHttpError as exc:
        print(f"Harness HTTP error: {exc} :: {exc.body}")
        return 1
    finally:
        http_client.close()


if __name__ == "__main__":
    raise SystemExit(run())

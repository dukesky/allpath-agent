from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from allpath_agent.agent import AgentLoop, BudgetExceededError, IterationLimitError
from allpath_agent.application import AgentApplication, demo_profiles
from allpath_agent.config import AppConfig, ConfigError, load_config, resolve_home, write_default_config
from allpath_agent.curriculum import CurriculumEngine, CurriculumService, default_capabilities
from allpath_agent.models import DemoProvider, ModelRouter, ProviderError, ProviderPool
from allpath_agent.observability import JsonlEventLogger
from allpath_agent.provider_runtime import (
    available_provider_ids,
    build_provider_pool,
    provider_statuses,
)
from allpath_agent.storage import (
    CapabilityProgressRepository,
    CapabilitySuggestionRepository,
    CurriculumSessionRepository,
    Database,
    MemoryRepository,
    MessageRepository,
    RoutingDecisionRepository,
    SessionRepository,
    ToolApprovalRepository,
    ToolExecutionRepository,
)
from allpath_agent.tools import ToolRuntime, create_builtin_registry

from .approvals import TerminalApprovalHandler


Output = Callable[[str], None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="allpath-agent", description="Run Allpath Agent locally")
    parser.add_argument("--home", help="Override the Allpath Agent home directory")
    parser.add_argument("--demo", action="store_true", help="Run locally without an API key")
    parser.add_argument("--session", help="Resume an existing session ID")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("init", help="Create a starter configuration file")
    sessions = subparsers.add_parser("sessions", help="List recent sessions")
    sessions.add_argument("--limit", type=int, default=20)
    subparsers.add_parser("providers", help="Show configured model providers and auth status")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = resolve_home(args.home)
    try:
        if args.command == "init":
            return _initialize(home)
        if args.command == "providers":
            return _show_providers(load_config(home / "config.toml"), print)
        database = Database(home / "state.db")
        database.initialize()
        if args.command == "sessions":
            return _list_sessions(SessionRepository(database), args.limit, print)
        return _chat(home, database, args.demo, args.session, input, print, _stderr)
    except ConfigError as error:
        _stderr(f"Configuration error: {error}")
        return 2
    except OSError as error:
        _stderr(f"Local runtime error: {error}")
        return 1


def _initialize(home: Path) -> int:
    config_path = home / "config.toml"
    write_default_config(config_path)
    print(f"Created {config_path}")
    print("Edit provider settings and model names, then set the configured API key variables.")
    print("You can run 'allpath-agent --demo' immediately without an API key.")
    return 0


def _chat(
    home: Path,
    database: Database,
    demo: bool,
    requested_session_id: str | None,
    input_fn: Callable[[str], str],
    output: Output,
    error_output: Output,
) -> int:
    sessions = SessionRepository(database)
    messages = MessageRepository(database)
    if requested_session_id:
        session = sessions.get(requested_session_id)
        if session is None:
            raise ConfigError(f"session does not exist: {requested_session_id}")
    else:
        session = sessions.create()

    application = _build_application(home, database, demo, input_fn, output)
    application.start_session(session.id)
    if requested_session_id:
        application.record_capability_success("session_management")
    mode = "demo" if demo else "live"
    output(f"Allpath Agent ({mode} mode)")
    output(f"Session: {session.id}")
    output("Type /help for commands or /exit to quit.")

    active_session_id = session.id
    while True:
        try:
            user_message = input_fn("You> ").strip()
        except EOFError:
            output("")
            output("Goodbye.")
            return 0
        except KeyboardInterrupt:
            output("")
            output("Interrupted. Session state is saved.")
            return 130

        if not user_message:
            continue
        if user_message in {"/exit", "/quit"}:
            output("Goodbye.")
            return 0
        if user_message == "/help":
            output(
                "Commands: /help, /new, /sessions, /resume <session-id>, "
                "/capabilities, /dismiss [capability-id], /exit"
            )
            continue
        if user_message == "/new":
            active_session_id = sessions.create().id
            application.start_session(active_session_id)
            application.record_capability_success("session_management")
            output(f"New session: {active_session_id}")
            continue
        if user_message == "/sessions":
            _list_sessions(sessions, 20, output)
            application.record_capability_success("session_management")
            continue
        if user_message.startswith("/resume "):
            candidate_id = user_message.removeprefix("/resume ").strip()
            if sessions.get(candidate_id) is None:
                error_output(f"Session does not exist: {candidate_id}")
            else:
                active_session_id = candidate_id
                application.start_session(active_session_id)
                application.record_capability_success("session_management")
                output(f"Resumed session: {active_session_id}")
            continue
        if user_message == "/capabilities":
            for capability_id, title, status in application.capability_progress():
                output(f"{capability_id:<20} {status:<10} {title}")
            continue
        if user_message == "/dismiss" or user_message.startswith("/dismiss "):
            capability_id = user_message.removeprefix("/dismiss").strip() or None
            if application.dismiss_suggestion(active_session_id, capability_id):
                output("Capability suggestion dismissed.")
            else:
                error_output("No capability suggestion found to dismiss.")
            continue

        try:
            current_session = sessions.get(active_session_id)
            if current_session and current_session.title is None:
                sessions.set_title(active_session_id, user_message[:60])
            result = application.send(active_session_id, user_message)
        except KeyboardInterrupt:
            _close_interrupted_turn(messages, active_session_id)
            output("")
            output("Task interrupted. You can continue in the same session.")
            continue
        except (
            BudgetExceededError,
            IterationLimitError,
            ProviderError,
            ValueError,
            KeyError,
        ) as error:
            _close_interrupted_turn(messages, active_session_id)
            error_output(f"Task failed: {error}")
            continue
        output(f"Agent [{result.agent.model_profile}]> {result.agent.content}")
        if result.agent.usage_reported:
            output(
                f"Usage: calls={result.agent.model_calls} "
                f"tokens={result.agent.total_tokens} "
                f"estimated_cost=${result.agent.estimated_cost_usd:.6f}"
            )
        if result.suggestion:
            output(f"Tip [{result.suggestion.capability_id}]: {result.suggestion.message}")


def _build_application(
    home: Path,
    database: Database,
    demo: bool,
    input_fn: Callable[[str], str],
    output: Output,
) -> AgentApplication:
    if demo:
        provider = ProviderPool.single(DemoProvider())
        profiles = demo_profiles()
        system_prompt = "You are Allpath Agent running in deterministic offline demo mode."
        max_model_calls = 12
        max_task_tokens = 100_000
        max_task_cost_usd = 0.0
        advanced_threshold = 6
    else:
        config = load_config(home / "config.toml")
        if any(profile.model.startswith("replace-with-") for profile in config.models):
            raise ConfigError("config.toml still contains placeholder model values")
        provider = build_provider_pool(config)
        profiles = config.models
        system_prompt = config.agent.system_prompt
        max_model_calls = config.agent.max_model_calls
        max_task_tokens = config.agent.max_task_tokens
        max_task_cost_usd = config.agent.max_task_cost_usd
        advanced_threshold = config.agent.advanced_threshold

    memories = MemoryRepository(database)
    approvals = ToolApprovalRepository(database)
    tool_executions = ToolExecutionRepository(database)
    runtime = ToolRuntime(
        create_builtin_registry(memories),
        approvals,
        TerminalApprovalHandler(input_fn, output),
    )
    loop = AgentLoop(
        provider,
        MessageRepository(database),
        tool_executions,
        runtime,
        max_model_calls=max_model_calls,
        max_task_tokens=max_task_tokens,
        max_task_cost_usd=max_task_cost_usd,
        event_logger=JsonlEventLogger(home / "logs" / "agent.jsonl"),
    )
    curriculum = CurriculumService(
        CurriculumEngine(default_capabilities()),
        CapabilityProgressRepository(database),
        CapabilitySuggestionRepository(database),
        CurriculumSessionRepository(database),
    )
    return AgentApplication(
        loop,
        ModelRouter(list(profiles), advanced_threshold=advanced_threshold),
        RoutingDecisionRepository(database),
        tool_executions,
        approvals,
        curriculum,
        system_prompt,
        live_provider=not demo,
    )


def _list_sessions(sessions: SessionRepository, limit: int, output: Output) -> int:
    if limit < 1:
        raise ConfigError("session limit must be positive")
    records = sessions.list_recent(limit)
    if not records:
        output("No sessions yet.")
        return 0
    for session in records:
        title = session.title or "Untitled"
        output(f"{session.id}  {session.updated_at}  {title}")
    return 0


def _show_providers(config: AppConfig, output: Output) -> int:
    for status in provider_statuses(config):
        if status.auth == "external_cli":
            state = "available" if status.connected else "missing"
        else:
            state = "connected" if status.connected else "missing"
        profiles = ",".join(status.model_profiles) or "unused"
        output(
            f"{status.id:<16} {state:<10} {status.protocol:<26} "
            f"profiles={profiles}  {status.detail}"
        )
    output(f"Built-in provider types: {', '.join(available_provider_ids())}")
    return 0


def _close_interrupted_turn(messages: MessageRepository, session_id: str) -> None:
    history = messages.list_for_session(session_id)
    if not history:
        return
    last = history[-1]
    if last.role == "assistant" and not last.metadata.get("tool_calls"):
        return
    if last.role == "assistant":
        for tool_call in last.metadata.get("tool_calls") or []:
            messages.append(
                session_id,
                "tool",
                '{"ok": false, "error": {"type": "Interrupted", "message": "task interrupted"}}',
                tool_call_id=tool_call["id"],
            )
    messages.append(session_id, "assistant", "Task interrupted before completion.")


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import getpass
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from allpath_agent.agent import AgentLoop, BudgetExceededError, IterationLimitError
from allpath_agent.application import AgentApplication, demo_profiles
from allpath_agent.config import AppConfig, ConfigError, load_config, resolve_home, write_default_config
from allpath_agent.curriculum import CurriculumEngine, CurriculumService, default_capabilities
from allpath_agent.connectors import (
    ConnectorRegistry,
    ConnectorRuntime,
    SlackConnector,
    TelegramConnector,
    WhatsAppConnector,
    diagnose_connectors,
)
from allpath_agent.models import DemoProvider, ModelRouter, ProviderError, ProviderPool
from allpath_agent.gateway_service import GatewayServiceManager
from allpath_agent.observability import JsonlEventLogger
from allpath_agent.provider_runtime import (
    available_provider_ids,
    build_provider_pool,
    provider_statuses,
)
from allpath_agent.secrets import SecretStore
from allpath_agent.storage import (
    CapabilityProgressRepository,
    CapabilitySuggestionRepository,
    ConnectorConfigRepository,
    ConnectorSessionRepository,
    CurriculumSessionRepository,
    Database,
    MemoryRepository,
    MessageRepository,
    RoutingDecisionRepository,
    SessionRepository,
    ToolApprovalRepository,
    ToolExecutionRepository,
    WorkflowRunRepository,
)
from allpath_agent.tools import ToolRuntime, create_builtin_registry
from allpath_agent.workflows import (
    ProviderConnectionWorkflow,
    SlackConnectionWorkflow,
    TelegramConnectionWorkflow,
    WhatsAppConnectionWorkflow,
    reassign_model_role,
    remove_model_role,
    verify_provider_connection,
)

from .account_auth import ensure_codex_login
from .approvals import TerminalApprovalHandler
from .banner import launch_lines
from .selector import terminal_select


Output = Callable[[str], None]
Selector = Callable[[str, Sequence[str], bool], int | None]


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
    connectors = subparsers.add_parser("connectors", help="Show messaging connector status")
    connectors.add_argument("--test", action="store_true", help="Verify credentials and runtime readiness")
    gateway = subparsers.add_parser("gateway", help="Run configured messaging connectors")
    gateway.add_argument("action", nargs="?", choices=("run", "install", "status", "restart", "uninstall"), default="run")
    gateway.add_argument("--once", action="store_true", help="Poll once and exit")
    gateway.add_argument("--poll-interval", type=float, default=1.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = resolve_home(args.home)
    try:
        if args.command == "init":
            return _initialize(home)
        if args.command == "providers":
            environment = SecretStore(home / "secrets.json").merged_environment()
            return _show_providers(
                load_config(home / "config.toml"),
                print,
                environment,
            )
        database = Database(home / "state.db")
        database.initialize()
        if args.command == "connectors":
            if args.test:
                return _test_connectors(home, ConnectorConfigRepository(database), print)
            return _show_connectors(ConnectorConfigRepository(database), print)
        if args.command == "gateway":
            if args.action != "run":
                return _manage_gateway_service(home, args.action, print)
            return _run_gateway(home, database, args.once, args.poll_interval, print, _stderr)
        if args.command == "sessions":
            return _list_sessions(SessionRepository(database), args.limit, print)
        starter_mode = not (home / "config.toml").is_file()
        return _chat(
            home,
            database,
            args.demo or starter_mode,
            args.session,
            input,
            print,
            _stderr,
            getpass.getpass,
            terminal_select,
        )
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
    print("Run 'allpath-agent' to chat after replacing the placeholder model names.")
    return 0


def _chat(
    home: Path,
    database: Database,
    demo: bool,
    requested_session_id: str | None,
    input_fn: Callable[[str], str],
    output: Output,
    error_output: Output,
    secret_input_fn: Callable[[str], str] | None = None,
    selector_fn: Selector | None = None,
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
    connection_workflow = ProviderConnectionWorkflow(
        home / "config.toml",
        WorkflowRunRepository(database),
        SecretStore(home / "secrets.json"),
    )
    telegram_workflow = TelegramConnectionWorkflow(
        WorkflowRunRepository(database),
        SecretStore(home / "secrets.json"),
        ConnectorConfigRepository(database),
    )
    slack_workflow = SlackConnectionWorkflow(
        WorkflowRunRepository(database),
        SecretStore(home / "secrets.json"),
        ConnectorConfigRepository(database),
    )
    whatsapp_workflow = WhatsAppConnectionWorkflow(
        WorkflowRunRepository(database),
        SecretStore(home / "secrets.json"),
        ConnectorConfigRepository(database),
    )
    hidden_input = secret_input_fn or getpass.getpass
    application.start_session(session.id)
    if requested_session_id:
        application.record_capability_success("session_management")
    live_mode = not demo
    configured_roles = ()
    configured_connectors = ()
    if live_mode:
        configured_roles = tuple(profile.name for profile in load_config(home / "config.toml").models)
        configured_connectors = tuple(
            record["connector_id"]
            for record in ConnectorConfigRepository(database).list_all()
            if record["status"] == "active"
        )
    for line in launch_lines(
        live_mode=live_mode,
        session_id=session.id,
        configured_roles=configured_roles,
        configured_connectors=configured_connectors,
        capability_progress=application.capability_progress(),
    ):
        output(line)

    active_session_id = session.id
    while True:
        try:
            input_hint = connection_workflow.input_hint(active_session_id)
            if input_hint is None:
                input_hint = slack_workflow.input_hint(active_session_id)
            if input_hint is None:
                input_hint = whatsapp_workflow.input_hint(active_session_id)
            if input_hint is None:
                input_hint = telegram_workflow.input_hint(active_session_id)
            if input_hint is None and not live_mode:
                input_hint = "Try: 连接模型 · what can you do · calculate 18 * 7"
            prompt = f"You>  ({input_hint})\n> " if input_hint else "You> "
            user_message = input_fn(prompt).strip()
        except EOFError:
            output("")
            output("Goodbye.")
            return 0
        except KeyboardInterrupt:
            output("")
            output("Interrupted. Session state is saved.")
            return 130
        except UnicodeDecodeError:
            error_output("Input contained an incomplete character. Please type it again.")
            continue

        if not user_message and not connection_workflow.active(active_session_id):
            continue
        if user_message in {"/exit", "/quit"}:
            output("Goodbye.")
            return 0
        if user_message == "/help":
            output(
                "Commands: /help, /new, /sessions, /resume <session-id>, "
                "/model, /models, /route, /connectors, /capabilities, "
                "/dismiss [capability-id], /exit"
            )
            continue
        if user_message.startswith("/help "):
            output("/help does not take a question. Ask it directly, for example: what should I do next?")
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
        if user_message == "/route":
            _show_latest_route(RoutingDecisionRepository(database), active_session_id, output)
            continue
        if user_message in {"/connectors", "/connectors test"}:
            if user_message.endswith(" test"):
                _test_connectors(home, ConnectorConfigRepository(database), output)
            else:
                _show_connectors(ConnectorConfigRepository(database), output)
            continue
        if user_message in {"/model", "/models current"}:
            _show_current_model(home, database, active_session_id, output)
            continue
        if user_message == "/models" or user_message.startswith("/models "):
            action = user_message.removeprefix("/models").strip()
            if not (home / "config.toml").is_file():
                output("No live models are configured. Starting model connection.")
                user_message = "connect model"
            elif action:
                changed = _run_model_subcommand(home, action, output, error_output)
                if changed:
                    application = _build_application(home, database, False, input_fn, output)
                    application.start_session(active_session_id)
                continue
            else:
                _show_models(load_config(home / "config.toml"), output)
                if selector_fn is None:
                    output("Use /models test, /models move <from> <to>, or /models remove <role>.")
                    continue
                selected = selector_fn(
                    "Manage models",
                    (
                        "Add or replace a model",
                        "Test all model connections",
                        "Reassign a model role",
                        "Remove a model role",
                        "Explain the latest route",
                    ),
                    False,
                )
                if selected is None:
                    continue
                if selected == 0:
                    user_message = "connect model"
                elif selected == 1:
                    _test_models(home, output)
                    continue
                elif selected == 2:
                    if _select_role_reassignment(home, selector_fn, output, error_output):
                        application = _build_application(home, database, False, input_fn, output)
                        application.start_session(active_session_id)
                    continue
                elif selected == 3:
                    if _select_role_removal(home, selector_fn, output, error_output):
                        application = _build_application(home, database, False, input_fn, output)
                        application.start_session(active_session_id)
                    continue
                else:
                    _show_latest_route(RoutingDecisionRepository(database), active_session_id, output)
                    continue
        if user_message == "/dismiss" or user_message.startswith("/dismiss "):
            capability_id = user_message.removeprefix("/dismiss").strip() or None
            if application.dismiss_suggestion(active_session_id, capability_id):
                output("Capability suggestion dismissed.")
            else:
                error_output("No capability suggestion found to dismiss.")
            continue

        if (
            _requests_telegram_setup(user_message)
            or _requests_slack_setup(user_message)
            or _requests_whatsapp_setup(user_message)
        ) and not (home / "config.toml").is_file():
            output("Agent [setup]> Connect a reasoning model first, then connect a messaging channel.")
            continue
        whatsapp_result = whatsapp_workflow.handle(active_session_id, user_message)
        if whatsapp_result.handled:
            for message in whatsapp_result.messages:
                output(f"Agent [setup]> {message}")
            while whatsapp_result.request_secret:
                try:
                    secret = hidden_input(whatsapp_workflow.secret_prompt(active_session_id))
                except (EOFError, KeyboardInterrupt):
                    output("")
                    error_output("Secret input cancelled. WhatsApp setup is still resumable.")
                    break
                whatsapp_result = whatsapp_workflow.submit_secret(active_session_id, secret)
                for message in whatsapp_result.messages:
                    output(f"Agent [setup]> {message}")
            continue
        slack_result = slack_workflow.handle(active_session_id, user_message)
        if slack_result.handled:
            for message in slack_result.messages:
                output(f"Agent [setup]> {message}")
            while slack_result.request_secret:
                try:
                    secret = hidden_input(slack_workflow.secret_prompt(active_session_id))
                except (EOFError, KeyboardInterrupt):
                    output("")
                    error_output("Secret input cancelled. Slack setup is still resumable.")
                    break
                slack_result = slack_workflow.submit_secret(active_session_id, secret)
                for message in slack_result.messages:
                    output(f"Agent [setup]> {message}")
            continue
        telegram_result = telegram_workflow.handle(active_session_id, user_message)
        if telegram_result.handled:
            for message in telegram_result.messages:
                output(f"Agent [setup]> {message}")
            if telegram_result.request_secret:
                try:
                    token = hidden_input("Telegram bot token (hidden)> ")
                except (EOFError, KeyboardInterrupt):
                    output("")
                    error_output("Secret input cancelled. Telegram setup is still resumable.")
                    continue
                telegram_result = telegram_workflow.submit_secret(active_session_id, token)
                for message in telegram_result.messages:
                    output(f"Agent [setup]> {message}")
            continue

        connection_result = connection_workflow.handle(
            active_session_id,
            user_message,
        )
        if connection_result.handled:
            for message in connection_result.messages:
                output(f"Agent [setup]> {message}")
            if selector_fn is not None:
                connection_result = _run_connection_selectors(
                    connection_workflow,
                    active_session_id,
                    connection_result,
                    selector_fn,
                    output,
                )
            if connection_result.request_secret:
                try:
                    secret = hidden_input("API key (hidden)> ")
                except (EOFError, KeyboardInterrupt):
                    output("")
                    error_output("Secret input cancelled. Connection setup is still resumable.")
                    continue
                connection_result = connection_workflow.submit_secret(
                    active_session_id,
                    secret,
                )
                for message in connection_result.messages:
                    output(f"Agent [setup]> {message}")
                if selector_fn is not None and not connection_result.request_secret:
                    connection_result = _run_connection_selectors(
                        connection_workflow,
                        active_session_id,
                        connection_result,
                        selector_fn,
                        output,
                    )
            if connection_result.completed:
                live_mode = True
                application = _build_application(
                    home,
                    database,
                    False,
                    input_fn,
                    output,
                )
                application.start_session(active_session_id)
                application.record_capability_success("live_provider")
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


def _run_connection_selectors(
    workflow: ProviderConnectionWorkflow,
    session_id: str,
    result,
    selector: Selector,
    output: Output,
):
    while result.handled and not result.request_secret and not result.completed:
        step = workflow.current_step(session_id)
        if step == "choose_provider":
            selected = selector(
                "Connect a model — choose provider",
                workflow.provider_options(),
                False,
            )
            if selected is None:
                return result
            result = workflow.handle(session_id, str(selected + 1))
        elif step == "choose_model":
            provider_id = workflow.selected_provider(session_id)
            if provider_id == "openai-codex":
                connected, message, command = ensure_codex_login()
                output(f"Agent [setup]> {message}")
                if not connected:
                    return workflow.handle(session_id, "cancel")
                workflow.set_external_command(session_id, command)
            models = workflow.model_options(session_id)
            if not models:
                return result
            selected = selector("Choose a model — / to search", models, True)
            if selected is None:
                return result
            result = workflow.handle(session_id, models[selected])
        elif step == "choose_profile":
            selected = selector("Assign model role", workflow.profile_options(), False)
            if selected is None:
                return result
            result = workflow.handle(session_id, str(selected + 1))
        else:
            return result
        for message in result.messages:
            output(f"Agent [setup]> {message}")
        if step == "choose_profile":
            return result
    return result


def _build_application(
    home: Path,
    database: Database,
    demo: bool,
    input_fn: Callable[[str], str],
    output: Output,
    interactive_approvals: bool = True,
) -> AgentApplication:
    if demo:
        provider = ProviderPool.single(DemoProvider())
        profiles = demo_profiles()
        system_prompt = "You are Allpath Agent running in deterministic offline demo mode."
        max_model_calls = 12
        max_task_tokens = 100_000
        max_task_cost_usd = 0.0
        provider_max_attempts = 3
        retry_base_delay_seconds = 0.5
        retry_max_delay_seconds = 8.0
        advanced_threshold = 6
    else:
        config = load_config(home / "config.toml")
        if any(profile.model.startswith("replace-with-") for profile in config.models):
            raise ConfigError("config.toml still contains placeholder model values")
        environment = SecretStore(home / "secrets.json").merged_environment()
        provider = build_provider_pool(config, environment)
        profiles = config.models
        system_prompt = config.agent.system_prompt
        max_model_calls = config.agent.max_model_calls
        max_task_tokens = config.agent.max_task_tokens
        max_task_cost_usd = config.agent.max_task_cost_usd
        provider_max_attempts = config.agent.provider_max_attempts
        retry_base_delay_seconds = config.agent.retry_base_delay_seconds
        retry_max_delay_seconds = config.agent.retry_max_delay_seconds
        advanced_threshold = config.agent.advanced_threshold

    memories = MemoryRepository(database)
    approvals = ToolApprovalRepository(database)
    tool_executions = ToolExecutionRepository(database)
    runtime = ToolRuntime(
        create_builtin_registry(memories),
        approvals,
        TerminalApprovalHandler(input_fn, output) if interactive_approvals else None,
    )
    loop = AgentLoop(
        provider,
        MessageRepository(database),
        tool_executions,
        runtime,
        max_model_calls=max_model_calls,
        max_task_tokens=max_task_tokens,
        max_task_cost_usd=max_task_cost_usd,
        provider_max_attempts=provider_max_attempts,
        retry_base_delay_seconds=retry_base_delay_seconds,
        retry_max_delay_seconds=retry_max_delay_seconds,
        event_logger=JsonlEventLogger(home / "logs" / "agent.jsonl"),
    )
    curriculum = CurriculumService(
        CurriculumEngine(default_capabilities()),
        CapabilityProgressRepository(database),
        CapabilitySuggestionRepository(database),
        CurriculumSessionRepository(database),
        suppressed_capability_ids=(
            {"model_routing", "live_provider"} if demo else set()
        ),
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


def _show_providers(
    config: AppConfig,
    output: Output,
    environment: dict[str, str] | None = None,
) -> int:
    for status in provider_statuses(config, environment):
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


def _show_connectors(configs: ConnectorConfigRepository, output: Output) -> int:
    records = configs.list_all()
    if not records:
        output("No messaging connectors configured. Try: connect Telegram")
        return 0
    for record in records:
        output(f"{record['connector_id']:<12} {record['status']:<9} {record['detail']}")
    return 0


def _test_connectors(home: Path, configs: ConnectorConfigRepository, output: Output) -> int:
    records = configs.list_all()
    if not records:
        output("No messaging connectors configured. Try: connect Telegram")
        return 0
    secrets = SecretStore(home / "secrets.json").values()
    for diagnostic in diagnose_connectors(records, secrets):
        output(f"{diagnostic.connector_id}:")
        output(f"  credentials: {diagnostic.credentials}")
        output(f"  verification: {diagnostic.verification}")
        output(f"  runtime: {diagnostic.runtime}")
        output(f"  next: {diagnostic.action}")
    return 0


def _requests_telegram_setup(message: str) -> bool:
    lowered = message.lower()
    return "telegram" in lowered and any(
        phrase in lowered for phrase in ("connect", "setup", "set up", "连接", "配置", "设置")
    )


def _requests_slack_setup(message: str) -> bool:
    lowered = message.lower()
    return "slack" in lowered and any(
        phrase in lowered for phrase in ("connect", "setup", "set up", "连接", "配置", "设置")
    )


def _requests_whatsapp_setup(message: str) -> bool:
    lowered = message.lower()
    return "whatsapp" in lowered and any(
        phrase in lowered for phrase in ("connect", "setup", "set up", "连接", "配置", "设置")
    )


def _run_gateway(
    home: Path,
    database: Database,
    once: bool,
    poll_interval: float,
    output: Output,
    error_output: Output,
) -> int:
    if poll_interval < 0:
        raise ConfigError("gateway poll interval cannot be negative")
    configs = ConnectorConfigRepository(database).list_all()
    active_ids = {record["connector_id"] for record in configs if record["status"] == "active"}
    if not active_ids:
        raise ConfigError("No active connectors. Connect Telegram, Slack, or WhatsApp in Allpath first")
    secrets = SecretStore(home / "secrets.json").values()
    connectors = []
    if "telegram" in active_ids:
        token = secrets.get("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ConfigError("Telegram token is missing; reconnect Telegram")
        connectors.append(TelegramConnector(token))
    if "slack" in active_ids:
        bot_token = secrets.get("SLACK_BOT_TOKEN")
        app_token = secrets.get("SLACK_APP_TOKEN")
        if not bot_token or not app_token:
            raise ConfigError("Slack tokens are missing; reconnect Slack")
        connectors.append(SlackConnector(bot_token, app_token))
    if "whatsapp" in active_ids:
        access_token = secrets.get("WHATSAPP_ACCESS_TOKEN")
        phone_number_id = secrets.get("WHATSAPP_PHONE_NUMBER_ID")
        app_secret = secrets.get("WHATSAPP_APP_SECRET")
        verify_token = secrets.get("WHATSAPP_VERIFY_TOKEN")
        if not all((access_token, phone_number_id, app_secret, verify_token)):
            raise ConfigError("WhatsApp credentials are missing; reconnect WhatsApp")
        connectors.append(
            WhatsAppConnector(access_token, phone_number_id, app_secret, verify_token)
        )
    statuses = [connector.status() for connector in connectors]
    failed = next((status for status in statuses if not status.connected), None)
    if failed:
        raise ConfigError(f"{failed.id} verification failed: {failed.detail}")
    application = _build_application(
        home,
        database,
        False,
        lambda prompt: "",
        output,
        interactive_approvals=False,
    )
    registry = ConnectorRegistry(tuple(connectors))
    runtime = ConnectorRuntime(
        application,
        registry,
        SessionRepository(database),
        ConnectorSessionRepository(database),
    )
    output("Allpath gateway running: " + ", ".join(f"{status.id} {status.detail}" for status in statuses))
    output("Side-effecting tools are denied unless a channel-safe approval flow is added.")
    try:
        runtime.start_all()
        while True:
            for connector_id in registry.ids():
                processed = runtime.poll_once(connector_id)
                if processed:
                    output(f"{connector_id}: processed {processed} message(s)")
            if once:
                return 0
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        output("")
        output("Gateway stopped. Session mappings are saved.")
        return 130
    except Exception as error:
        error_output(f"Gateway error: {type(error).__name__}: {str(error)[:240]}")
        return 1
    finally:
        runtime.stop_all()


def _manage_gateway_service(home: Path, action: str, output: Output) -> int:
    manager = GatewayServiceManager(home)
    try:
        if action == "install":
            status = manager.install()
        elif action == "status":
            status = manager.status()
        elif action == "restart":
            status = manager.restart()
        elif action == "uninstall":
            status = manager.uninstall()
        else:
            raise ConfigError(f"unknown gateway service action: {action}")
    except RuntimeError as error:
        raise ConfigError(str(error)) from error
    state = "running" if status.running else "stopped"
    installed = "installed" if status.installed else "not installed"
    output(f"Gateway service: {installed}, {state} ({status.detail})")
    if status.installed:
        output(f"Service file: {manager.service_path}")
        output(f"Logs: {home / 'logs' / 'gateway.out.log'}")
    return 0


def _show_models(config: AppConfig, output: Output) -> None:
    profiles = {profile.name: profile for profile in config.models}
    output("Model roles:")
    for role in ("fast", "standard", "advanced"):
        profile = profiles.get(role)
        if profile is None:
            output(f"{role:<10} not configured")
        else:
            output(f"{role:<10} {profile.model:<28} provider={profile.provider}")


def _run_model_subcommand(home: Path, action: str, output: Output, error_output: Output) -> bool:
    parts = action.split()
    try:
        if parts == ["test"]:
            _test_models(home, output)
            return False
        if len(parts) == 3 and parts[0] == "move":
            reassign_model_role(home / "config.toml", parts[1], parts[2])
            output(f"Model role moved: {parts[1]} → {parts[2]}.")
            return True
        if len(parts) == 2 and parts[0] == "remove":
            removed_provider = remove_model_role(home / "config.toml", parts[1])
            output(f"Removed model role: {parts[1]}.")
            if removed_provider:
                output(f"Unused provider {removed_provider} was removed; its saved credential was retained.")
            return True
    except (ConfigError, ValueError) as error:
        error_output(f"Model management failed: {error}")
        return False
    error_output("Usage: /models test | /models move <from> <to> | /models remove <role>")
    return False


def _test_models(home: Path, output: Output) -> None:
    config = load_config(home / "config.toml")
    environment = SecretStore(home / "secrets.json").merged_environment()
    for profile in sorted(config.models, key=lambda item: item.name):
        provider = config.providers[profile.provider]
        secret = environment.get(provider.api_key_env, "") if provider.api_key_env else ""
        try:
            verify_provider_connection(provider, profile, secret)
        except Exception as error:
            output(f"{profile.name:<10} failed  {type(error).__name__}: {str(error)[:160]}")
        else:
            output(f"{profile.name:<10} ok      {profile.provider}/{profile.model}")


def _select_role_reassignment(home: Path, selector: Selector, output: Output, error_output: Output) -> bool:
    config = load_config(home / "config.toml")
    roles = tuple(profile.name for profile in config.models)
    source = selector("Move which configured role?", roles, False)
    if source is None:
        return False
    targets = tuple(
        role
        for role in ("fast", "standard", "advanced")
        if role not in roles
    )
    if not targets:
        error_output("All model roles are configured; use Add or replace a model instead.")
        return False
    target = selector("Assign it to which role?", targets, False)
    if target is None:
        return False
    return _run_model_subcommand(
        home,
        f"move {roles[source]} {targets[target]}",
        output,
        error_output,
    )


def _select_role_removal(home: Path, selector: Selector, output: Output, error_output: Output) -> bool:
    config = load_config(home / "config.toml")
    roles = tuple(profile.name for profile in config.models)
    selected = selector("Remove which role?", roles, False)
    if selected is None:
        return False
    confirmed = selector(f"Remove {roles[selected]}?", ("Cancel", "Remove model role"), False)
    if confirmed != 1:
        return False
    return _run_model_subcommand(home, f"remove {roles[selected]}", output, error_output)


def _show_latest_route(repository: RoutingDecisionRepository, session_id: str, output: Output) -> None:
    decision = repository.latest_for_session(session_id)
    if decision is None:
        output("No routing decision has been recorded in this session yet.")
        return
    output(f"Routed to: {decision['profile']}")
    output(f"Reason: {decision['reason']}")
    output(f"Provider: {decision['provider']}")
    output(f"Model: {decision['model']}")


def _show_current_model(home: Path, database: Database, session_id: str, output: Output) -> None:
    if not (home / "config.toml").is_file():
        output("Current mode: local starter")
        output("Provider: default")
        output("Model roles: demo-fast, demo-advanced")
        return
    config = load_config(home / "config.toml")
    decision = RoutingDecisionRepository(database).latest_for_session(session_id)
    if decision is not None:
        profile = next(
            (item for item in config.models if item.name == decision["profile"]),
            None,
        )
        if profile is not None:
            provider = config.providers[profile.provider]
            output(f"Current role: {profile.name}")
            output(f"Provider: {profile.provider}")
            output(f"Model: {profile.model}")
            output(f"Allpath tools: {'enabled' if profile.supports_tools else 'not available'}")
            if provider.id == "openai-codex":
                output("Provider sandbox: read-only (Codex CLI)")
            return
    output("No model has been used in this session yet. Configured roles:")
    _show_models(config, output)


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

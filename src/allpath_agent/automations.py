from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from allpath_agent.storage import (
    AutomationJobRepository,
    AutomationRunRepository,
    SessionRepository,
    ToolApprovalRepository,
)
from allpath_agent.hooks import HookBus


class AutomationApplication(Protocol):
    def start_session(self, session_id: str) -> None: ...

    def send(self, session_id: str, message: str, *, record_curriculum: bool = True) -> Any: ...


Deliverer = Callable[[str, str, str], str]


@dataclass(frozen=True)
class CronSchedule:
    expression: str
    timezone: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    day_wildcard: bool
    weekday_wildcard: bool

    def next_after(self, moment: datetime) -> datetime:
        if moment.tzinfo is None:
            raise ValueError("schedule calculation requires a timezone-aware datetime")
        candidate = moment.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = candidate + timedelta(days=366 * 5)
        timezone = ZoneInfo(self.timezone)
        while candidate <= limit:
            local = candidate.astimezone(timezone)
            cron_weekday = (local.weekday() + 1) % 7
            day_matches = local.day in self.days
            weekday_matches = cron_weekday in self.weekdays
            if self.day_wildcard:
                calendar_matches = weekday_matches
            elif self.weekday_wildcard:
                calendar_matches = day_matches
            else:
                calendar_matches = day_matches or weekday_matches
            if (
                local.minute in self.minutes
                and local.hour in self.hours
                and local.month in self.months
                and calendar_matches
            ):
                return candidate
            candidate += timedelta(minutes=1)
        raise ValueError("cron schedule has no occurrence within five years")


def parse_cron(expression: str, timezone: str) -> CronSchedule:
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"unknown IANA timezone: {timezone}") from error
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("cron expression must contain five fields: minute hour day month weekday")
    minute, hour, day, month, weekday = fields
    return CronSchedule(
        expression=" ".join(fields),
        timezone=timezone,
        minutes=_parse_field(minute, 0, 59, "minute"),
        hours=_parse_field(hour, 0, 23, "hour"),
        days=_parse_field(day, 1, 31, "day"),
        months=_parse_field(month, 1, 12, "month"),
        weekdays=_parse_field(weekday, 0, 7, "weekday", normalize_sunday=True),
        day_wildcard=day == "*",
        weekday_wildcard=weekday == "*",
    )


def parse_once(value: str, timezone: str) -> datetime:
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"unknown IANA timezone: {timezone}") from error
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(cleaned)
    except ValueError as error:
        raise ValueError("one-time schedule must be an ISO date/time") from error
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(UTC)


class AutomationService:
    def __init__(
        self,
        jobs: AutomationJobRepository,
        runs: AutomationRunRepository,
        sessions: SessionRepository,
        application: AutomationApplication | None = None,
        now: Callable[[], datetime] | None = None,
        hooks: HookBus | None = None,
        approvals: ToolApprovalRepository | None = None,
        deliver: Deliverer | None = None,
    ):
        self.jobs = jobs
        self.runs = runs
        self.sessions = sessions
        self.application = application
        self._now = now or (lambda: datetime.now(UTC))
        self._hooks = hooks or HookBus()
        self._approvals = approvals
        self._deliver_fn = deliver

    def create_once(
        self,
        name: str,
        prompt: str,
        at: str,
        timezone: str,
        *,
        model_role: str = "auto",
        destination_connector_id: str | None = None,
        destination_conversation_id: str | None = None,
    ) -> dict[str, Any]:
        next_run = parse_once(at, timezone)
        if next_run <= self._now().astimezone(UTC):
            raise ValueError("one-time automation must be scheduled in the future")
        session = self.sessions.create(title=f"automation:{name.strip()}")
        return self.jobs.create(
            name=name,
            prompt=prompt,
            schedule_kind="once",
            schedule_expression=at.strip(),
            timezone=timezone,
            session_id=session.id,
            next_run_at=next_run.isoformat(),
            model_role=model_role,
            destination_connector_id=destination_connector_id,
            destination_conversation_id=destination_conversation_id,
        )

    def create_cron(
        self,
        name: str,
        prompt: str,
        expression: str,
        timezone: str,
        *,
        model_role: str = "auto",
        destination_connector_id: str | None = None,
        destination_conversation_id: str | None = None,
    ) -> dict[str, Any]:
        schedule = parse_cron(expression, timezone)
        next_run = schedule.next_after(self._now())
        session = self.sessions.create(title=f"automation:{name.strip()}")
        return self.jobs.create(
            name=name,
            prompt=prompt,
            schedule_kind="cron",
            schedule_expression=schedule.expression,
            timezone=timezone,
            session_id=session.id,
            next_run_at=next_run.isoformat(),
            model_role=model_role,
            destination_connector_id=destination_connector_id,
            destination_conversation_id=destination_conversation_id,
        )

    def run_now(self, job_id: str) -> dict[str, Any]:
        self._require_application()
        job = self.jobs.get(job_id)
        if job is None:
            raise ValueError(f"automation job does not exist: {job_id}")
        run = self.runs.claim_now(job_id, self._now().astimezone(UTC).isoformat())
        return self._execute(job, run, advance_schedule=False)

    def tick(self) -> dict[str, Any] | None:
        self._require_application()
        claimed = self.runs.claim_due(self._now().astimezone(UTC).isoformat())
        if claimed is None:
            return None
        return self._execute(claimed["job"], claimed["run"], advance_schedule=True)

    def _require_application(self) -> None:
        if self.application is None:
            raise RuntimeError("automation execution requires an AgentApplication")

    def _execute(
        self,
        job: dict[str, Any],
        run: dict[str, Any],
        *,
        advance_schedule: bool,
    ) -> dict[str, Any]:
        self.runs.start(run["id"])
        try:
            result = self.application.send(job["session_id"], job["prompt"], record_curriculum=False)
            needs_attention = self._denied_side_effects(job["session_id"], result.task_id)
            delivered_id, delivery_error = self._deliver(job, result.agent.content)
            if delivery_error is None:
                finished = self.runs.finish(
                    run["id"],
                    "succeeded",
                    task_id=result.task_id,
                    output_text=result.agent.content,
                    output_message_id=delivered_id,
                    needs_attention=needs_attention,
                )
            else:
                finished = self.runs.finish(
                    run["id"],
                    "failed",
                    task_id=result.task_id,
                    output_text=result.agent.content,
                    error_type="DeliveryError",
                    error_message=delivery_error,
                    needs_attention=True,
                )
        except KeyboardInterrupt:
            finished = self.runs.finish(run["id"], "interrupted", error_type="KeyboardInterrupt", error_message="automation interrupted")
        except Exception as error:
            finished = self.runs.finish(
                run["id"],
                "failed",
                error_type=type(error).__name__,
                error_message=str(error),
            )
        if advance_schedule:
            self._advance(job, finished)
        self._hooks.emit(
            "automation_run_completed",
            job_id=job["id"],
            run_id=finished["id"],
            status=finished["status"],
            session_id=job["session_id"],
        )
        return finished

    def _denied_side_effects(self, session_id: str, task_id: str) -> bool:
        if self._approvals is None:
            return False
        return any(
            record["decision"] == "denied"
            for record in self._approvals.list_for_task(session_id, task_id)
        )

    def _deliver(self, job: dict[str, Any], text: str) -> tuple[str | None, str | None]:
        if job["destination_connector_id"] is None:
            return None, None
        if self._deliver_fn is None:
            return None, "no delivery channel is available in this process"
        try:
            message_id = self._deliver_fn(
                job["destination_connector_id"],
                job["destination_conversation_id"],
                text,
            )
        except Exception as error:
            return None, f"{type(error).__name__}: {str(error)[:160]}"
        return message_id, None

    def _advance(self, job: dict[str, Any], run: dict[str, Any]) -> None:
        now = self._now().astimezone(UTC)
        if job["schedule_kind"] == "once":
            self.jobs.complete_schedule(
                job["id"],
                last_run_at=run["scheduled_for"],
                next_run_at=None,
                disable=True,
            )
            return
        try:
            schedule = parse_cron(job["schedule_expression"], job["timezone"])
            next_run = schedule.next_after(max(now, datetime.fromisoformat(run["scheduled_for"])))
        except ValueError:
            self.jobs.complete_schedule(
                job["id"],
                last_run_at=run["scheduled_for"],
                next_run_at=None,
                disable=True,
            )
            return
        self.jobs.complete_schedule(
            job["id"],
            last_run_at=run["scheduled_for"],
            next_run_at=next_run.isoformat(),
            disable=False,
        )


def _parse_field(
    value: str,
    minimum: int,
    maximum: int,
    label: str,
    *,
    normalize_sunday: bool = False,
) -> frozenset[int]:
    selected: set[int] = set()
    for part in value.split(","):
        if not part:
            raise ValueError(f"invalid empty {label} field")
        base, separator, step_text = part.partition("/")
        step = 1
        if separator:
            try:
                step = int(step_text)
            except ValueError as error:
                raise ValueError(f"invalid {label} step: {step_text}") from error
            if step < 1:
                raise ValueError(f"{label} step must be positive")
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = _integer(start_text, label), _integer(end_text, label)
        else:
            start = end = _integer(base, label)
        if start < minimum or end > maximum or start > end:
            raise ValueError(f"{label} value must be between {minimum} and {maximum}")
        selected.update(range(start, end + 1, step))
    if normalize_sunday and 7 in selected:
        selected.remove(7)
        selected.add(0)
    return frozenset(selected)


def _integer(value: str, label: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"invalid {label} value: {value}") from error

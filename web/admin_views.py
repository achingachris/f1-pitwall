"""Custom Django admin views for Pitwall.

Currently: a live "what's running" page that queries Celery's worker via
broadcast inspect calls. Read-only — for editing schedules or browsing
task history, use the django-celery-beat / django-celery-results pages
that the packages ship.
"""

from datetime import datetime, timezone

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from celery import current_app


def _flatten(by_worker: dict | None) -> list[dict]:
    """Celery inspect() returns {worker_name: [task, task, ...]}. Flatten to
    a list of tasks annotated with their worker so the template doesn't have
    to deal with the per-worker grouping."""
    out = []
    for worker, tasks in (by_worker or {}).items():
        for t in tasks or []:
            out.append({**t, "_worker": worker})
    return out


def _epoch_to_dt(epoch):
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


@staff_member_required
def celery_status(request):
    """Live worker + task snapshot. Uses control.inspect() which broadcasts
    over the broker and waits for replies; timeout keeps the admin
    responsive even when no workers are up."""
    inspect = current_app.control.inspect(timeout=2)

    active = _flatten(inspect.active())
    reserved = _flatten(inspect.reserved())
    scheduled = _flatten(inspect.scheduled())
    stats = inspect.stats() or {}
    registered = inspect.registered() or {}

    # Annotate active tasks with started timestamp.
    for t in active:
        t["_started_at"] = _epoch_to_dt(t.get("time_start"))

    workers = []
    for name, s in stats.items():
        workers.append(
            {
                "name": name,
                "pool": s.get("pool", {}).get("implementation", "?"),
                "processes": s.get("pool", {}).get("processes", []),
                "total": s.get("total", {}),
                "uptime": s.get("uptime"),
                "tasks": sorted(registered.get(name, [])),
            }
        )

    return render(
        request,
        "admin/celery_status.html",
        {
            "title": "Celery — live status",
            "workers": workers,
            "active": active,
            "reserved": reserved,
            "scheduled": scheduled,
            "no_workers": not workers,
        },
    )

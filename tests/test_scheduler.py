from adi.engine.scheduler import Scheduler


def test_scheduler_eligible_filters_by_state_dependencies_policy_and_running() -> None:
    scheduler = Scheduler()
    tasks = [
        {
            "id": "TK-001",
            "status": "approved",
            "depends_on": [],
            "priority": "medium",
            "size": "small",
            "created_at": "2026-03-10T00:00:00+00:00",
        },
        {
            "id": "TK-002",
            "status": "approved",
            "depends_on": ["TK-004"],
            "priority": "medium",
            "size": "small",
            "created_at": "2026-03-10T00:00:00+00:00",
        },
        {
            "id": "TK-003",
            "status": "proposed",
            "depends_on": [],
            "priority": "high",
            "size": "small",
            "created_at": "2026-03-10T00:00:00+00:00",
        },
        {
            "id": "TK-004",
            "status": "completed",
            "depends_on": [],
            "priority": "low",
            "size": "small",
            "created_at": "2026-03-10T00:00:00+00:00",
        },
    ]

    policy_actions = {
        "TK-001": "auto_execute",
        "TK-002": "auto_execute",
        "TK-003": "auto_execute",
        "TK-004": "auto_execute",
    }

    eligible = scheduler.eligible(
        tasks,
        running_task_ids={"TK-001"},
        policy_actions=policy_actions,
    )
    assert [task["id"] for task in eligible] == ["TK-002"]


def test_scheduler_rank_prioritizes_priority_size_and_creation_time() -> None:
    scheduler = Scheduler()
    tasks = [
        {
            "id": "TK-LOW",
            "status": "approved",
            "depends_on": [],
            "priority": "low",
            "size": "small",
            "created_at": "2026-03-10T00:00:01+00:00",
        },
        {
            "id": "TK-HIGH-MEDIUM",
            "status": "approved",
            "depends_on": [],
            "priority": "high",
            "size": "medium",
            "created_at": "2026-03-10T00:00:02+00:00",
        },
        {
            "id": "TK-HIGH-SMALL-OLDER",
            "status": "approved",
            "depends_on": [],
            "priority": "high",
            "size": "small",
            "created_at": "2026-03-10T00:00:00+00:00",
        },
    ]

    ranked = scheduler.rank(tasks)
    assert [task["id"] for task in ranked] == [
        "TK-HIGH-SMALL-OLDER",
        "TK-HIGH-MEDIUM",
        "TK-LOW",
    ]

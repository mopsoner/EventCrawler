from unittest.mock import call, patch

import scheduler


def test_main_initializes_app_then_booking_worker_then_scheduler_loop():
    calls = []

    with (
        patch.object(scheduler, "create_app", side_effect=lambda: calls.append(call.create_app())),
        patch.object(
            scheduler,
            "ensure_booking_job_thread",
            side_effect=lambda: calls.append(call.ensure_booking_job_thread()),
        ),
        patch.object(scheduler, "scheduler_loop", side_effect=lambda: calls.append(call.scheduler_loop())),
    ):
        scheduler.main()

    assert calls == [call.create_app(), call.ensure_booking_job_thread(), call.scheduler_loop()]

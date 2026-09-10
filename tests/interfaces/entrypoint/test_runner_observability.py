import pytest

from reuleauxcoder.interfaces.entrypoint.runner import AppRunner


@pytest.mark.parametrize("error_type", [ValueError, SystemExit])
def test_startup_callback_failure_is_logged_and_propagated(error_type, caplog) -> None:
    failure = error_type("startup progress failed")

    def fail_progress(_message: str) -> None:
        raise failure

    runner = AppRunner(startup_progress=fail_progress)

    with pytest.raises(error_type) as raised:
        runner.initialize()

    assert raised.value is failure
    record = caplog.records[-1]
    assert "startup_progress/callback" in record.message
    assert record.exc_info[1] is failure
    assert record.exc_info[2] is not None
    assert "startup progress failed" in caplog.text

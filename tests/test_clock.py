from datetime import datetime, timezone

from twin.clock import to_local_standard


def test_denver_summer_and_winter_use_standard_time():
    summer = datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc)
    winter = datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc)
    # 18:00 UTC is 12:00 MDT and 11:00 MST. Standard time drops the DST hour.
    assert to_local_standard(summer, "America/Denver") == datetime(2026, 7, 15, 11, 0)
    assert to_local_standard(winter, "America/Denver") == datetime(2026, 1, 15, 11, 0)

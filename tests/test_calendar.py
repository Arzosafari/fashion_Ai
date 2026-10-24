from datetime import datetime, timezone
from trend_system.utils.calendar import to_jalali_dict, jalali_season

def test_jalali_conversion():
    # 2026-09-21 should be 1405-06-30
    dt = datetime(2026,9,21,4,30, tzinfo=timezone.utc)
    j = to_jalali_dict(dt)
    assert j["jalali_date"] == "1405-06-30"
    assert j["season"] == "summer"  # Shahrivar is summer
    assert j["gregorian_date"] == "2026-09-21"
    assert "timestamp_utc" in j

def test_jalali_season():
    assert jalali_season(1) == "spring"
    assert jalali_season(4) == "summer"
    assert jalali_season(7) == "autumn"
    assert jalali_season(10) == "winter"

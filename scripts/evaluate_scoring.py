"""Evaluation methodology for tuning scoring parameters — prevents temporal leakage"""
from datetime import datetime, timezone, timedelta
from trend_system.scoring.trend_score import compute_trend_score_for_signals

# Example: grid search over half_life
search_space = {
    "half_life_days": [7,14,30,60,90],
    "window_days": [14,30,60],
}

def evaluate_half_life():
    """Demo: how to evaluate without leakage — use only data <= snapshot_time"""
    now = datetime.now(timezone.utc)
    # Simulate 30 days of signals for a concept
    signals = []
    for i in range(30):
        signals.append({
            "timestamp_utc": now - timedelta(days=i),
            "confidence": 0.8,
            "authority_weight": 0.7,
            "source_id": "vogue" if i%2==0 else "digikala_mag",
            "region": "global" if i%2==0 else "iranian",
            "language": "en" if i%2==0 else "fa",
        })
    # Time-based split: train on first 20 days, test on last 10
    train_signals = [s for s in signals if s["timestamp_utc"] <= now - timedelta(days=10)]
    test_signals = [s for s in signals if s["timestamp_utc"] > now - timedelta(days=10)]

    for hl in search_space["half_life_days"]:
        cfg = {"half_life_days": hl, "window_days":30, "decay_type":"exponential", "bundle_weights":{"G":1,"C":0.8,"P":1,"R":1.2,"Gw":0.7,"S":0.6}, "gate":{"I_weight":1.0}, "seasonal":{}}
        # In real evaluation, compute precision@k vs human labels per snapshot
        # Here just demo that train/test are separated
        score_train, _ = compute_trend_score_for_signals(train_signals, "wide_leg_bottom", now - timedelta(days=10), "summer", scoring_cfg=cfg)
        print(f"half_life {hl}: train_score={score_train:.3f} (using only data <= train_end)")

if __name__ == "__main__":
    print("Evaluation methodology — leakage-free, time-based splits")
    print("All queries must filter WHERE timestamp_utc <= :snapshot_time")
    evaluate_half_life()
    print("Done — extend with human-labeled validation set for precision/recall")

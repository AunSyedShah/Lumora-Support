"""
Complaint analytics (SRS Step 64) and trend detection (Step 65), computed with pandas.

Trend rules (all thresholds are parameters, so they can be shown and changed in a demo):
  rising            in the current window a value has >= min_count complaints AND grew by
                    >= growth (e.g. 0.5 = +50%) compared with the previous window of equal length
  recurring issue   the same product + subcategory at least `recurring_min` times in the last 30 days
  repeated failure  repeat / near-duplicate complaints grouped by subcategory in the window
  escalation spike  a day with >= spike_min escalations and more than mean + 2 x std of the
                    preceding days in the last 30 days
"""

from datetime import timedelta

import pandas as pd
from django.utils import timezone

from rules.models import ESCALATION_RANK


def _count_list(series, total):
    counts = series.fillna("unknown").replace("", "unknown").value_counts()
    return [
        {"value": str(value), "count": int(count), "percent": round(100 * count / total, 1) if total else 0.0}
        for value, count in counts.items()
    ]


def distribution(df, column, limit=None):
    items = _count_list(df[column], len(df)) if len(df) else []
    return items[:limit] if limit else items


def resolution_time(df):
    hours = df["resolution_hours"].dropna()
    if hours.empty:
        return {"resolved": 0, "mean_hours": None, "median_hours": None, "p90_hours": None, "by_priority": []}
    by_priority = (
        df.dropna(subset=["resolution_hours"]).groupby("priority")["resolution_hours"].agg(["count", "mean", "median"])
    )
    return {
        "resolved": int(hours.count()),
        "mean_hours": round(float(hours.mean()), 1),
        "median_hours": round(float(hours.median()), 1),
        "p90_hours": round(float(hours.quantile(0.9)), 1),
        "by_priority": [
            {"priority": p, "resolved": int(row["count"]), "mean_hours": round(float(row["mean"]), 1),
             "median_hours": round(float(row["median"]), 1)}
            for p, row in by_priority.iterrows()
        ],
    }


def analytics(df):
    total = len(df)
    if total == 0:
        return {"total": 0}
    escalated = df[df["escalated"]]
    levels = sorted(escalated["escalation_level"].unique(), key=lambda l: -ESCALATION_RANK.get(l, 0))
    volume = df.groupby("date").size()
    scores = df["verification_score"].dropna()
    repeats = df[df["is_repeat"]]
    return {
        "total": total,
        "open": int(df["is_open"].sum()),
        "resolved_or_closed": int((~df["is_open"]).sum()),
        "volume_by_day": [{"date": str(d), "count": int(n)} for d, n in volume.items()],
        "by_category": distribution(df, "category"),
        "by_subcategory": distribution(df, "subcategory", limit=15),
        "by_product": distribution(df, "product"),
        "by_department": distribution(df, "department"),
        "by_urgency": distribution(df, "urgency"),
        "by_priority": distribution(df, "priority"),
        "by_sentiment": distribution(df, "sentiment"),
        "by_status": distribution(df, "status"),
        "by_channel": distribution(df, "channel"),
        "by_customer_type": distribution(df, "customer_type"),
        "escalations": {
            "total": len(escalated),
            "rate_percent": round(100 * len(escalated) / total, 1),
            "by_level": [{"level": l, "count": int((escalated["escalation_level"] == l).sum())} for l in levels],
        },
        "resolution_time": resolution_time(df),
        "repeat_complaints": {
            "count": len(repeats),
            "rate_percent": round(100 * len(repeats) / total, 1),
            "by_subcategory": distribution(repeats, "subcategory", limit=10) if len(repeats) else [],
        },
        "sla": {
            "resolution": distribution(df, "sla_resolution"),
            "response": distribution(df, "sla_response"),
        },
        "verification": {
            "by_status": distribution(df, "verification_status"),
            "average_score": round(float(scores.mean()), 1) if not scores.empty else None,
            "manual_review_pending": int(df["review_status"].isin(["pending", "rejected"]).sum()),
        },
    }


# ---------------- trends ----------------


def detect_trends(df, window_days=7, min_count=3, growth=0.5, recurring_min=3, spike_min=3, now=None):
    now = now or timezone.now()
    current_start = now - timedelta(days=window_days)
    previous_start = now - timedelta(days=2 * window_days)
    if df.empty:
        return {"window_days": window_days, "rising": [], "recurring_product_issues": [],
                "repeated_service_failures": [], "escalation_spikes": []}

    current = df[df["created_at"] > current_start]
    previous = df[(df["created_at"] > previous_start) & (df["created_at"] <= current_start)]

    rising = []
    for dimension in ("category", "subcategory", "product", "department"):
        now_counts = current[dimension].dropna().value_counts()
        before_counts = previous[dimension].dropna().value_counts()
        for value, count in now_counts.items():
            before = int(before_counts.get(value, 0))
            change = (count - before) / before if before else None
            if count >= min_count and (before == 0 or change >= growth):
                rising.append({
                    "dimension": dimension, "value": value, "current": int(count), "previous": before,
                    "change_percent": round(100 * change, 1) if change is not None else None,
                    "message": f"{dimension} {value}: {count} complaints in the last {window_days} days "
                               f"(previous {window_days} days: {before}).",
                })
    rising.sort(key=lambda r: -r["current"])

    last_30 = df[df["created_at"] > now - timedelta(days=30)]
    recurring = (
        last_30.dropna(subset=["product", "subcategory"]).groupby(["product", "subcategory"]).size()
        .sort_values(ascending=False)
    )
    recurring_issues = [
        {"product": p, "subcategory": s, "count_30_days": int(n),
         "message": f"{p}: {n} '{s}' complaints in the last 30 days."}
        for (p, s), n in recurring.items() if n >= recurring_min
    ]

    repeated = current[current["is_repeat"]].dropna(subset=["subcategory"]).groupby("subcategory").size()
    repeated_failures = [
        {"subcategory": s, "repeat_complaints": int(n),
         "message": f"{n} customers complained again about {s} in the last {window_days} days."}
        for s, n in repeated.sort_values(ascending=False).items() if n >= 2
    ]

    daily = last_30[last_30["escalated"]].groupby("date").size()
    spikes = []
    days = pd.date_range((now - timedelta(days=29)).date(), now.date()).date
    series = pd.Series([int(daily.get(d, 0)) for d in days], index=days)
    for i, (day, count) in enumerate(series.items()):
        history = series.iloc[:i]
        if len(history) < 3 or count < spike_min:
            continue
        threshold = history.mean() + 2 * history.std()
        if count > threshold:
            spikes.append({"date": str(day), "escalations": int(count), "threshold": round(float(threshold), 1),
                           "message": f"{count} escalations on {day} (normal is below {threshold:.1f})."})

    return {
        "window_days": window_days,
        "rising": rising,
        "recurring_product_issues": recurring_issues,
        "repeated_service_failures": repeated_failures,
        "escalation_spikes": spikes,
    }

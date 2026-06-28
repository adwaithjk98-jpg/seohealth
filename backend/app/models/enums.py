import enum


class UserPlan(str, enum.Enum):
    free = "free"
    # ``paid`` is the Pro tier (single business + the quality loop). ``max`` is
    # the multi-location / agency tier. Both are "paying" tiers — gates that
    # used to test ``!= paid`` must test ``== free`` so Max users aren't locked
    # out of Pro features.
    paid = "paid"
    max = "max"


class AuditStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class AuditTrigger(str, enum.Enum):
    manual = "manual"
    scheduled = "scheduled"


class AuditSectionName(str, enum.Enum):
    maps = "maps"
    website = "website"
    instagram = "instagram"
    nap = "nap"
    competitors = "competitors"
    # Site-speed / Core Web Vitals pillar, sourced from the Google PageSpeed
    # Insights API (HTTP, no headless browser). See scrapers/pagespeed.py.
    performance = "performance"


class AuditSectionStatus(str, enum.Enum):
    done = "done"
    failed = "failed"
    partial = "partial"


class RecommendationSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class RecommendationFixStatus(str, enum.Enum):
    open = "open"
    done = "done"
    dismissed = "dismissed"


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    cancelled = "cancelled"
    past_due = "past_due"


class DiscoveryScanStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"

"""Deterministic 0–100 "Overall Visibility" score.

Used for the Market matrix row that shows where the user and each tracked
competitor sit on the same scale. The formula intentionally avoids any
LLM or learned weights — it normalises the three signals we observe
across both sides (rating, review_count, instagram_followers) and blends
them with fixed weights so the score is reproducible and auditable.

Design notes
------------

* The user's own business has a richer composite score from the full
  audit (``Audit.sections`` → ``_audit_overall_score``). That score
  stays on ``BusinessResponse.latest_score`` for the dashboard. The
  visibility score *here* is a separate, narrower metric that compares
  apples to apples across the user and competitors. The Market matrix
  uses this one; the dashboard summary uses the audit composite.

* Each component is normalised to [0, 1]. Review and follower counts
  are log-scaled because doubling from 50→100 reviews matters more than
  doubling from 5000→10000.

* Missing inputs are dropped and the remaining weights are renormalised,
  but only as long as **at least two** of the three signals are present.
  Renormalising on a single signal made a business with just a 5★ rating
  read as "100 (1st)" on the matrix even when reviews + IG were
  completely unknown — that's overconfident. With ``< 2`` signals we
  return ``None`` (the matrix renders that as "—"), so the ranking
  reflects breadth of evidence, not just one lucky number.
"""

from __future__ import annotations

import math

_RATING_MIN = 1.0
_RATING_MAX = 5.0
# Reviews: 1000 reviews ≈ "well-established". log10(1000)=3 is the
# numerator's ceiling for normalisation.
_REVIEWS_CEILING = 1000
# IG followers: 100k followers ≈ "well-established local presence".
_IG_FOLLOWERS_CEILING = 100_000

_WEIGHT_RATING = 0.40
_WEIGHT_REVIEWS = 0.30
_WEIGHT_IG_FOLLOWERS = 0.30


def _normalised_rating(rating: float) -> float:
    if rating <= _RATING_MIN:
        return 0.0
    if rating >= _RATING_MAX:
        return 1.0
    return (rating - _RATING_MIN) / (_RATING_MAX - _RATING_MIN)


def _log_normalised(value: int, ceiling: int) -> float:
    if value <= 1:
        return 0.0
    # log10(value) / log10(ceiling) clipped to [0, 1].
    raw = math.log10(value) / math.log10(ceiling)
    if raw <= 0:
        return 0.0
    if raw >= 1:
        return 1.0
    return raw


def compute(
    rating: float | None,
    review_count: int | None,
    instagram_followers: int | None,
) -> int | None:
    """Return a 0–100 integer visibility score, or ``None`` if no inputs.

    The blend renormalises across whichever signals are present so the
    output reflects the strength of what *is* observed rather than
    silently penalising entities with sparse data.
    """
    components: list[tuple[float, float]] = []
    if rating is not None:
        components.append((_normalised_rating(float(rating)), _WEIGHT_RATING))
    if review_count is not None:
        components.append(
            (_log_normalised(int(review_count), _REVIEWS_CEILING), _WEIGHT_REVIEWS)
        )
    if instagram_followers is not None:
        components.append(
            (
                _log_normalised(int(instagram_followers), _IG_FOLLOWERS_CEILING),
                _WEIGHT_IG_FOLLOWERS,
            )
        )
    # Require at least two of {rating, reviews, ig_followers}. A single
    # signal renormalised to 100% weight made entities with only a
    # rating look like a perfect score — see module docstring.
    if len(components) < 2:
        return None
    total_weight = sum(w for _, w in components)
    if total_weight <= 0:
        return None
    weighted = sum(c * w for c, w in components) / total_weight
    return round(weighted * 100)

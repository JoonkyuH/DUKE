"""
signal_scorer.py
Computes normalized 0–100 scores for each of the six screening signals.

Each function accepts a sub-dict from a RawSignalRecord and returns a float in [0, 100].
NULL inputs (missing data) return None — callers must handle None scores explicitly.
A None score is NOT treated as zero; it is excluded from the composite calculation
with a proportional rebalance of remaining weights.

Signal definitions:
  1. Momentum          — price trend strength vs moving averages and ROC
  2. Relative Strength — outperformance vs market and sector
  3. Volume Anomaly    — unusual volume relative to recent average
  4. Sector Leadership — ticker rank within sector + sector rank vs market
  5. News Velocity     — acceleration of quality news coverage
  6. Earnings Proximity — catalyst window scoring
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SignalScores:
    momentum:           Optional[float]
    relative_strength:  Optional[float]
    volume_anomaly:     Optional[float]
    sector_leadership:  Optional[float]
    news_velocity:      Optional[float]
    earnings_proximity: Optional[float]


# ─────────────────────────────────────────────
# 1. MOMENTUM
# ─────────────────────────────────────────────

def score_momentum(price_data: dict) -> Optional[float]:
    """
    Measures the strength and consistency of the price trend.

    Components:
      - MA position:  price above 20d/50d/200d MAs            (0–45 pts)
      - 20-day ROC:   rate of change over 20 trading days      (0–25 pts)
      - 5-day ROC:    recent momentum confirmation             (0–15 pts)
      - RSI context:  healthy momentum range vs extremes       (0–15 pts, can penalize)

    Returns None if price_data is empty or missing all key fields.
    """
    if not price_data or "current_price" not in price_data:
        return None

    score = 0.0

    # --- MA Position (45 pts) ---
    if price_data.get("above_ma_200"):
        score += 15
    if price_data.get("above_ma_50"):
        score += 15
    if price_data.get("above_ma_20"):
        score += 15

    # --- 20-day Rate of Change (25 pts) ---
    change_20d = price_data.get("change_20d_pct", 0)
    if change_20d >= 15:    score += 25
    elif change_20d >= 10:  score += 20
    elif change_20d >= 5:   score += 15
    elif change_20d >= 2:   score += 8
    elif change_20d >= 0:   score += 3
    # < 0: no points

    # --- 5-day Rate of Change (15 pts, recency weight) ---
    change_5d = price_data.get("change_5d_pct", 0)
    if change_5d >= 5:      score += 15
    elif change_5d >= 3:    score += 10
    elif change_5d >= 1:    score += 5
    elif change_5d >= 0:    score += 2
    # < 0: no points

    # --- RSI Context (up to 15 pts, can subtract) ---
    rsi = price_data.get("rsi_14")
    if rsi is not None:
        if 55 <= rsi <= 70:    score += 15   # Healthy, unextended momentum
        elif 50 <= rsi < 55:   score += 8
        elif 70 < rsi <= 78:   score += 5    # Extended but not extreme
        elif rsi > 78:         score -= 5    # Overbought — penalize
        # rsi < 50: no points (bearish context)

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 2. RELATIVE STRENGTH
# ─────────────────────────────────────────────

def score_relative_strength(rs_data: dict) -> Optional[float]:
    """
    Measures outperformance vs the market (SPY) and the ticker's own sector.

    Components:
      - RS vs SPY 10d:          recent market outperformance    (0–25 pts)
      - RS vs SPY 20d:          sustained market outperformance (0–25 pts)
      - RS vs sector 10d:       sector-relative leadership      (0–25 pts)
      - Sector rank percentile: position within peer universe   (0–25 pts)

    Returns None if rs_data is missing all key fields.
    """
    if not rs_data:
        return None

    score = 0.0

    # --- RS vs SPY 10-day (25 pts) ---
    rs_spy_10 = rs_data.get("rs_vs_spy_10d", 0)
    if rs_spy_10 >= 5:      score += 25
    elif rs_spy_10 >= 3:    score += 20
    elif rs_spy_10 >= 1:    score += 12
    elif rs_spy_10 >= 0:    score += 5
    # < 0: no points (underperforming)

    # --- RS vs SPY 20-day (25 pts) ---
    rs_spy_20 = rs_data.get("rs_vs_spy_20d", 0)
    if rs_spy_20 >= 8:      score += 25
    elif rs_spy_20 >= 5:    score += 20
    elif rs_spy_20 >= 2:    score += 12
    elif rs_spy_20 >= 0:    score += 5

    # --- RS vs Sector 10-day (25 pts) ---
    rs_sect = rs_data.get("rs_vs_sector_10d", 0)
    if rs_sect >= 4:        score += 25
    elif rs_sect >= 2:      score += 18
    elif rs_sect >= 0.5:    score += 10
    elif rs_sect >= 0:      score += 4

    # --- Sector Rank Percentile (25 pts) ---
    rank_pct = rs_data.get("sector_rank_pct", 50)
    if rank_pct >= 90:      score += 25
    elif rank_pct >= 75:    score += 18
    elif rank_pct >= 60:    score += 10
    elif rank_pct >= 50:    score += 5

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 3. VOLUME ANOMALY
# ─────────────────────────────────────────────

def score_volume_anomaly(price_data: dict) -> Optional[float]:
    """
    Detects unusual volume relative to the 20-day average.
    High volume signals institutional participation; direction matters.

    Components:
      - Volume ratio vs 20d avg:   base score                  (0–90 pts)
      - Direction confirmation:    high-vol up day = bonus     (+10 pts)
                                   high-vol down day = penalty (−15 pts)

    Returns None if volume_ratio is not present.
    """
    if not price_data or "volume_ratio" not in price_data:
        return None

    vol_ratio = price_data["volume_ratio"]

    if vol_ratio >= 3.0:      score = 90
    elif vol_ratio >= 2.0:    score = 75
    elif vol_ratio >= 1.5:    score = 55
    elif vol_ratio >= 1.2:    score = 35
    elif vol_ratio >= 0.8:    score = 15
    else:                     score = 5    # Thin volume = weak signal

    # Direction confirmation
    change_1d = price_data.get("change_1d_pct", 0)
    if vol_ratio >= 1.5 and change_1d > 0:
        score = min(100, score + 10)       # High-vol up day: strong bullish signal
    elif vol_ratio >= 1.5 and change_1d < -1.5:
        score = max(0, score - 15)         # High-vol down day: distribution warning

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 4. SECTOR LEADERSHIP
# ─────────────────────────────────────────────

def score_sector_leadership(rs_data: dict, sector_data: dict) -> Optional[float]:
    """
    Evaluates whether the ticker is a leader within a strong sector.
    A strong stock in a weak sector scores lower than the same stock in a leading sector.

    Components:
      - Ticker rank within sector:  (0–50 pts, from rs_data.sector_rank_pct)
      - Sector RS vs market 20d:    (0–50 pts, from sector_data)

    Returns None if both data sources are empty.
    """
    if not rs_data and not sector_data:
        return None

    score = 0.0

    # --- Ticker rank within sector (50 pts) ---
    rank_pct = rs_data.get("sector_rank_pct", 50)
    score += (rank_pct / 100.0) * 50

    # --- Sector RS vs market (50 pts) ---
    sector_rs = sector_data.get("sector_rs_vs_spy_20d", 0)
    if sector_rs >= 5:      score += 50
    elif sector_rs >= 3:    score += 38
    elif sector_rs >= 1:    score += 25
    elif sector_rs >= 0:    score += 12
    elif sector_rs < 0:     score += 0    # Lagging sector reduces leadership value

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 5. NEWS VELOCITY
# ─────────────────────────────────────────────

def score_news_velocity(news_data: dict) -> Optional[float]:
    """
    Detects acceleration in quality news coverage.
    Per the evidence hierarchy, social sentiment receives low weight;
    source quality is applied as a multiplier on raw velocity.

    Components:
      - Velocity ratio:    today's count vs 7d average        (0–60 pts raw)
      - Source quality:    multiplier [0.5, 1.0] on velocity  (dampens low-quality signals)
      - Sentiment:         positive news adds pts; very negative subtracts

    Returns None if news_data is empty.
    """
    if not news_data:
        return None

    velocity   = news_data.get("velocity_ratio", 1.0)
    quality    = news_data.get("source_quality_score", 0.5)   # 0–1
    sentiment  = news_data.get("sentiment_score", 0.0)        # –1 to 1

    # --- Raw velocity score (60 pts) ---
    if velocity >= 5.0:    raw_vel = 60
    elif velocity >= 3.0:  raw_vel = 48
    elif velocity >= 2.0:  raw_vel = 36
    elif velocity >= 1.5:  raw_vel = 24
    elif velocity >= 1.0:  raw_vel = 12
    else:                  raw_vel = 0

    # Apply source quality dampener (social = 0.5× ; tier-1 press = 1.0×)
    score = raw_vel * (0.5 + quality * 0.5)

    # --- Sentiment modifier (0–40 pts, can penalize) ---
    if sentiment > 0.5:     score += 40
    elif sentiment > 0.2:   score += 25
    elif sentiment > 0:     score += 15
    elif sentiment < -0.5:  score -= 10    # Very negative news is a caution signal

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 6. EARNINGS PROXIMITY
# ─────────────────────────────────────────────

def score_earnings_proximity(earnings_data: dict) -> Optional[float]:
    """
    Scores catalyst proximity. Earnings reports are the primary hard catalyst.

    Pre-earnings window (0–30 days out) and post-earnings reaction window (0–7 days after)
    both contribute. The most recent EPS surprise amplifies the score.

    Returns None if earnings_data is empty.
    """
    if not earnings_data:
        return None

    days_to    = earnings_data.get("days_to_earnings", 999)
    days_since = earnings_data.get("days_since_earnings", 999)
    surprise   = earnings_data.get("last_eps_surprise_pct", 0)

    # --- Pre-earnings window ---
    if days_to <= 3:         score = 95    # Imminent — gap risk window
    elif days_to <= 7:       score = 85    # Strong pre-earnings buildup window
    elif days_to <= 14:      score = 72    # Active setup window
    elif days_to <= 30:      score = 50    # Worth monitoring
    elif days_to <= 60:      score = 25    # On radar
    else:                    score = 10    # Earnings far away

    # --- Post-earnings reaction window (take the higher of the two) ---
    if days_since <= 1:      score = max(score, 80)   # Fresh reaction — momentum setup
    elif days_since <= 3:    score = max(score, 60)
    elif days_since <= 7:    score = max(score, 40)

    # --- EPS surprise amplifier ---
    if abs(surprise) >= 15:
        score = min(100, score * 1.20)   # Large surprise = stronger signal
    elif abs(surprise) >= 8:
        score = min(100, score * 1.10)

    return min(100.0, max(0.0, score))

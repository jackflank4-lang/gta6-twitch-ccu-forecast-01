"""gta6-twitch-ccu-forecast-01: forecast GTA VI's launch-day Twitch viewers, hour by hour.

The program reads one case file (/input/<id>.in, schema makefun/twitch-ccu-case/v1)
and writes /output/<id>.out: for each of hours 2..24 of the release day (UTC), five
quantiles (5%, 25%, 50%, 75%, 95%) of that hour's concurrent Twitch viewers in the
Grand Theft Auto VI category. Standard library only, no network, deterministic.

Model -- a per-hour log-ratio regression on the case's own comparables
-----------------------------------------------------------------------
A launch's shape is stable only in *ratio* to its first hour: hour 1's print p1
already captures how big the launch is, and the rest of the day is mostly a
timezone-staggered unlock ramp (New Zealand first, then Asia, Europe, the UK,
the US east coast at 05:00Z and west coast at 08:00Z) riding Twitch's diurnal
curve (dead of night 01:00-04:00Z, evening peak 17:00-21:00Z). Across the 37 past
big launches in a practice case, the peak ratio is strongly tied to hour 1's
print (corr(log p1, peak log-ratio) = -0.94): a launch whose hour 1 already drew
875k viewers peaks barely above it, one whose hour 1 drew 23k peaks ~9x higher.

So, for each scored hour h = 2..24, separately:
  log(viewers_h / p1) = a_h + b_h * log(p1)          (OLS over the comparables)
with the slope shrunk 25% toward 0 (SHRINK = 0.75) and the intercept refit at the
shrunk slope -- the raw OLS slope overfits the contrast between tiny launches
(hour 1 near zero, ratios in the hundreds) and mega-launches. The median
forecast is the fitted value at the case's own log p1.

Two guards for the final, where GTA VI's hour 1 will sit far above anything in
the comparable set:
  * the effective log p1 is capped at log(300,000). Beyond that the model uses
    the shape of a 300k launch (peak ~1.3x hour 1), matching the biggest
    launches actually observed (The Last of Us Part II, 365k -> 1.34x; Diablo
    IV, 533k -> 1.26x; Hogwarts Legacy, 387k -> 1.30x), instead of
    extrapolating the log-linear fit to a flat or falling day. GTA VI unlocks
    rolling at midnight local with the US still pending at hour 1, so its day
    cannot peak at hour 1 the way a simultaneous global PC unlock
    (Cyberpunk 2077) did. The cap binds on no practice case (largest
    practice hour 1 is 269,517), so it changes nothing there.
  * the spread comes from the pooled residuals of the *large* comparables only
    (hour-1 print >= 25,000 viewers). Tiny launches have wildly skewed
    residuals that would blow the intervals up; the large-launch residuals are
    the honest uncertainty for a launch of this size. Quantiles are the pooled
    empirical residual quantiles at 0.05/0.25/0.75/0.95, scaled by SPREAD = 0.8,
    added to the median (q50 is the median itself). The residual distribution
    is asymmetric -- downside bounded, upside long -- which the empirical
    quantiles capture and a normal spread would not.

Fallbacks (the program must always write a valid forecast):
  * fewer than 5 usable comparable curves -> the house persistence baseline:
    q_tau = p1 * exp(z_tau * 0.15 * sqrt(h - 1)), z the normal quantiles.
  * no usable large comparable for the spread -> pooled residuals of all
    comparables; if there are none at all -> the baseline spread.
  * no hour-1 print -> the last history point's viewers, else 1.

Validation on the four practice cases (answers from SullyGnome's hourly
averages, the same source the cases were cut from; scorer = the rules' exact
pinball loss on the log scale):
  house baseline ......... loss 0.403, typical miss 85.9%, coverage 0.761
  this model ............. loss 0.186, typical miss ~28%,  coverage 0.898
  (per-case losses 0.19-0.27; the practice is a guide only -- the final is one
  launch, GTA VI, out of the comparables' range.)

Usage: mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
The grader runs: python3 -P -s /bot/main.py (Python 3.13, stdlib only).
"""

import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a helper module
# shipped beside this file would import. (This entry is a single file.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level (baseline fallback only).
Z = [-1.645, -0.674, 0, 0.674, 1.645]
# Spread of the house baseline's log random walk, per square-root hour.
BASELINE_SIGMA = 0.15

# --- Model constants (tuned on the four practice cases; see the docstring) ---
# Slope shrinkage for the per-hour log-ratio regression (1.0 = raw OLS).
SHRINK = 0.75
# Scale applied to the pooled empirical residual quantiles.
SPREAD = 0.8
# Effective hour-1 print is capped here (viewers) before the regression is
# evaluated -- see the docstring for why.
CAP_P1 = 300_000
# Only comparables at least this big (hour-1 viewers) contribute residuals to
# the spread; smaller launches' residuals are dominated by hour 1 being ~0.
RESID_P1_MIN = 25_000
# A comparable curve must cover hour 1 and at least this many scored hours.
MIN_SCORED_HOURS = 20
# Fewer usable comparable curves than this -> fall back to the baseline.
MIN_CURVES = 5


def parse_ts(text):
    """ISO 8601 UTC timestamp -> aware datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def round2(x):
    """x rounded to 2 decimals, half up, as JavaScript's Math.round does it.

    A whole number comes back as an int, so json.dumps writes 1240 where
    JavaScript writes 1240 (not 1240.0).
    """
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def quantile(sorted_values, q):
    """Linear-interpolation quantile of an already sorted list."""
    if not sorted_values:
        raise ValueError("quantile of an empty list")
    pos = q * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def ols(pairs):
    """Ordinary least squares y ~ a + b*x. Returns (intercept, slope)."""
    n = len(pairs)
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    b = sxy / sxx if sxx > 0 else 0.0
    return my - b * mx, b


def day_curve(comp):
    """A comparable's release-day hourly viewers, {hour 1..24: viewers}.

    Hours with no point, or a point of 0 viewers, are left out; the regression
    simply skips that (hour, comparable) pair.
    """
    day_start = parse_ts(comp["day_start"])
    out = {}
    for row in comp.get("hourly", []):
        viewers = row.get("viewers")
        if viewers is None or viewers <= 0:
            continue
        hour = int((parse_ts(row["from"]) - day_start).total_seconds() // 3600) + 1
        if 1 <= hour <= 24:
            out[hour] = viewers
    return out


def usable_curves(case):
    """The case's comparables as launch curves, minus the target's own history.

    The Grand Theft Auto VI entry in every case is the category's own
    pre-release hourly history, not a launch curve (its day_start is the
    2026-08-27 premiere, so its "release day" would be nonsense) -- it must
    never enter the fit.
    """
    curves = []
    for comp in case.get("comparables", []):
        if "Grand Theft Auto VI" in comp.get("name", ""):
            continue
        day = day_curve(comp)
        scored = [h for h in day if h >= 2]
        if 1 in day and len(scored) >= MIN_SCORED_HOURS:
            curves.append(
                {
                    "p1": day[1],
                    "ratios": {h: math.log(day[h] / day[1]) for h in scored},
                }
            )
    return curves


def hour1_print(case):
    """Hour 1's print (viewers), at least 1, with fallbacks."""
    for row in case.get("known", []):
        if row.get("hour") == 1 and row.get("viewers") is not None:
            return max(1, row["viewers"])
    history = case.get("history", [])
    if history:
        last = history[-1].get("viewers")
        if last is not None:
            return max(1, last)
    return 1


def baseline_quantiles(p1, hour):
    """The house persistence baseline's five quantiles for one hour."""
    return [
        round2(p1 * math.exp(z * BASELINE_SIGMA * math.sqrt(hour - 1))) for z in Z
    ]


def forecast_case(case, name):
    """The forecast object {"hours": [...]} for one case."""
    if case.get("levels") != LEVELS:
        raise ValueError(f"{name} asks for levels {case.get('levels')}, not {LEVELS}")
    p1 = hour1_print(case)
    hours = [row["hour"] for row in case.get("forecast", [])]
    if not hours:
        hours = list(range(2, 25))
    curves = usable_curves(case)

    if len(curves) < MIN_CURVES:
        # Not enough past launches to fit: persistence, the house baseline.
        return {
            "hours": [
                {"hour": h, "q": baseline_quantiles(p1, h)} for h in sorted(hours)
            ]
        }

    log_p1 = min(math.log(p1), math.log(CAP_P1))
    medians = {}
    residuals_all = []
    residuals_big = []
    for hour in range(2, 25):
        pairs = [
            (math.log(c["p1"]), c["ratios"][hour])
            for c in curves
            if hour in c["ratios"]
        ]
        if len(pairs) < 3:
            medians[hour] = 0.0
            continue
        intercept, slope = ols(pairs)
        slope *= SHRINK
        # Refit the intercept at the shrunk slope (OLS zeroes the mean
        # residual only at the raw slope; refitting keeps the fit centred).
        intercept = sum(y for _, y in pairs) / len(pairs) - slope * (
            sum(x for x, _ in pairs) / len(pairs)
        )
        medians[hour] = intercept + slope * log_p1
        for x, y in pairs:
            resid = y - (intercept + slope * x)
            residuals_all.append(resid)
            if math.exp(x) >= RESID_P1_MIN:
                residuals_big.append(resid)

    # The spread: pooled empirical residual quantiles of the large launches.
    # Fall back to all comparables' residuals, then to the baseline spread.
    pool = sorted(residuals_big) if residuals_big else sorted(residuals_all)
    if pool:
        offsets = [quantile(pool, t) * SPREAD for t in LEVELS]
    else:
        offsets = [z * BASELINE_SIGMA for z in Z]

    rows = []
    for hour in sorted(hours):
        median = medians.get(hour, 0.0)
        qs = [median + off for off in offsets]
        qs[2] = median
        qs = sorted(qs)
        # Round, clamp to the valid range, and keep the row non-decreasing.
        qs = [max(1.0, min(1e9, round2(p1 * math.exp(q)))) for q in qs]
        qs = sorted(qs)
        rows.append({"hour": hour, "q": qs})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        if len(text.encode("utf-8")) > 65536:
            raise ValueError(f"{path.name}: forecast over the 65,536-byte cap")
        (OUTPUT_DIR / f"{path.stem}.out").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

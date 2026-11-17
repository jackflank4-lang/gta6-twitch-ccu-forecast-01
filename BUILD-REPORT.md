# BUILD REPORT — gta6-twitch-ccu-forecast-01

**Repo:** https://github.com/jackflank4-lang/gta6-twitch-ccu-forecast-01
**Competition:** Forecast GTA VI's launch-day Twitch viewers hour by hour
(pot $250; 1st $50, 2nd $35, 3rd $25, 4th–10th $10, 11th–20th $7;
entries close 2026-11-19T01:00:00Z; escrow funded $250)
**Entry:** `main.py` (Python 3.13, standard library only) — the only entrypoint
(`main.ts` starter deleted). Built 17 Nov 2026, ~16:00–16:10 UTC, in one
session; no recording (bundle-based competition — the kit's `record` command
refuses it).

## What the program does

Reads `/input/<id>.in` (schema `makefun/twitch-ccu-case/v1`) and writes
`/output/<id>.out`: `{"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]},
...]}` — exactly 23 rows, hours 2..24, five quantiles per hour. It reads
`$MAKEFUN_INPUT_DIR` / `$MAKEFUN_OUTPUT_DIR` when set, else `/input` /
`/output`. Runtime ~0.07–0.08 s per case (cap 8 s). Deterministic: two runs
write byte-identical output.

## The model

Forecast each hour as a **ratio to hour 1's print**, fitted on the case's own
comparables (the 38 past big launches' hourly Twitch curves shipped in the
case file; the final case holds 42, the practice cases 38).

1. **Per-hour log-ratio regression.** For each scored hour h = 2..24:
   `log(viewers_h / p1) = a_h + b_h * log(p1)`, OLS over the comparable
   launches. The ratio's dependence on hour 1's print is the dominant
   structure in the data: corr(log p1, peak log-ratio) = **-0.94** across the
   37 usable comparables. Slopes run ~0 at hours 2–6 (the universal
   01:00–04:00Z dip) to about -0.9 at hours 17–24 (the evening peak).
2. **Slope shrinkage 0.75.** Raw OLS overfits the contrast between tiny
   launches (hour 1 near zero, peak ratios in the hundreds/thousands) and
   mega-launches; the intercept is refit at the shrunk slope.
3. **Hour-1 cap at 300,000 viewers.** The effective log p1 is capped before
   the regression is evaluated. Beyond the cap the model holds the shape of a
   300k launch (peak median ~1.30x hour 1 at hour 21). This matches the
   biggest launches actually observed (The Last of Us Part II 365k -> 1.34x;
   Diablo IV 533k -> 1.26x; Hogwarts Legacy 387k -> 1.30x) and respects the
   unlock physics: GTA VI unlocks rolling at midnight local with the US east
   coast at 05:00Z and west coast at 08:00Z still pending at hour 1, so its
   day cannot peak at hour 1 the way Cyberpunk 2077's simultaneous global
   PC unlock did (peak at hour 2, then falling all day). Uncapped, the
   log-linear fit would forecast a flat/falling day for any hour 1 above
   ~500k. The cap binds on no practice case (largest practice hour 1 is
   269,517), so it changes nothing there.
4. **Spread from large launches' residuals.** Quantiles are the pooled
   empirical residual quantiles (0.05/0.25/0.75/0.95) of comparables with
   hour-1 print >= 25,000, scaled by 0.8, added to the median (q50 is the
   median itself). The residual distribution is asymmetric (pooled quantiles
   q05 -1.01, q95 +0.60 for large launches): downside bounded, upside long.
   Tiny launches' residuals would blow the intervals up and were tested and
   rejected as a spread source. Fallback chain: all comparables' residuals,
   then the baseline spread.
5. **Fallbacks.** Fewer than 5 usable comparable curves -> the house
   persistence baseline (`q_tau = p1 * exp(z_tau * 0.15 * sqrt(h-1))`).
   Missing hour-1 print -> last history point's viewers, else 1. The
   Grand Theft Auto VI entry in every case is the category's own pre-release
   history, not a launch curve, and is explicitly excluded from the fit.
   Outputs are rounded to 2 decimals (half up), clamped to [1, 1e9], and
   sorted non-decreasing per row.

## How it was verified

**Practice answers.** The kit ships no answer files, so the four practice
answers were re-fetched from SullyGnome's chart API exactly as NOTICE.txt
documents
(`GET /api/charts/linecharts/getconfig/GameViewers/30/0/<id>/<name>/.../<YYYY>/<M>/...`,
"Average viewers" dataset, one month per launch) and cross-checked: the
hour-0 value matches each case's known hour-1 print exactly for all four
cases (23,357 / 116,550 / 269,517 / 119,087). Scoring uses the rules' exact
pinball loss: `2 * max(tau*d, (tau-1)*d)`, `d = ln(y) - ln(q)`, mean over
every (case, hour, level).

**Practice results** (4 cases x 23 hours x 5 levels = 460 items):

| entry | loss | typical miss | 90% coverage |
|---|---|---|---|
| house baseline (starter) | 0.4025 | 85.9% | 0.761 |
| this model | **0.1859** | **28.4%** | **0.898** |

Per-case losses: p00 Marvel's Wolverine 0.184, p01 Red Dead Redemption 2
0.223, p02 God of War Ragnarok 0.149, p03 Marvel's Spider-Man 2 0.188.
(The spec quotes the baseline at 0.387; my scorer reproduces 0.4025 on the
same cases -- likely a data-vintage difference. All comparisons above use
one scorer, so model selection is unaffected.)

**Tuning log** (all on the same 4 practice cases, same scorer):
- Empirical comparable quantiles (no regression): 0.3387.
- + log-p1 regression, shrink 0.75, empirical residuals: 0.2273.
- + residual spread 0.8: 0.2071; pooled residuals: 0.1946.
- + spread from large launches only (p1 >= 25k), spread 0.8: **0.1859**.
- Rejected (worse on practice): filtering comparables to the "comparable"
  tier only (0.3831); dropping tiny launches from the fit (0.27 -- the tiny
  launches carry the slope signal); adding log channels-1 (0.2123); adding a
  console-only indicator (0.2319); pooled-slope instead of per-hour slopes
  (0.3302); smoothing the median across hours (no gain). The final
  configuration sits in the middle of a flat plateau (0.19-0.21 across the
  neighbouring settings), not at a sharp optimum -- deliberately, since four
  practice cases cannot support fine tuning.

**Schema + determinism.** Every practice output was schema-checked
(exactly one top key `hours`, 23 rows, hours 2..24 each once, five finite
quantiles > 0 and <= 1e9, non-decreasing, <= 65,536 bytes) and run twice:
byte-identical.

**Edge cases** (synthetic cases, all valid output, no crash):
- Hour-1 print 1,000,000 / 1,500,000 / 3,000,000 -> peak median 1.30x at
  hour 21 (the cap working as designed), hour 24 ~1.07x.
- Hour-1 print 50 -> peak median 594x, all quantiles > 0.
- No comparables -> exact house baseline output.
- No `known` row -> falls back to the last history point (identical output
  to the unmodified case).

## Files

- `main.py` -- the entry (single file, Python 3.13 stdlib only)
- `README.md` -- entry summary, model, how to run, verification table
- `LICENSE` -- MIT (kit starter)
- `.makefun/owner.json` -- payout wallet (Merlin's Solana wallet)

## Notes for the submitter (parent)

- Do NOT submit without bundling this session's transcripts (bundle-based:
  `bundle --session <this session file>`); the build happened entirely in
  this session and no child sessions were used.
- The program uses only the case file's own comparables at run time, so the
  final case (42 comparables incl. the four practice launches) needs no code
  change.
- Practice scores are a guide only: the final is a single launch, GTA VI,
  whose hour-1 print will sit above the comparables' range -- the 300k cap
  is the deliberate guard for exactly that.

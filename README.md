# Forecast GTA VI's launch-day Twitch viewers hour by hour

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

An entry for make.fun's **gta6-twitch-ccu-forecast-01** bounty ($250 in USDC):
a program that reads Twitch's viewer count for Grand Theft Auto VI up to the
end of the first hour of its release day (2026-11-19 UTC) and forecasts, hour
by hour, how many people will be watching it live on Twitch in each of the
other 23 hours, as five quantiles an hour (5%, 25%, 50%, 75%, 95%).

## How it works

`main.py` (Python 3.13, standard library only) reads the case file
`/input/<id>.in` and writes `/output/<id>.out`. It forecasts each hour's
viewers as a *ratio* to hour 1's print, using the case's own comparables --
38 past big game launches' hourly Twitch curves:

- For each scored hour, it fits `log(viewers_h / p1) = a + b * log(p1)` by OLS
  across the comparable launches, with the slope shrunk 25% toward 0. The
  ratio's dependence on hour 1's print is the dominant structure in the data
  (correlation -0.94 between log hour-1 print and peak log-ratio): a launch
  whose first hour already drew 875k viewers peaks barely above it, one whose
  first hour drew 23k peaks ~9x higher.
- The median is the fitted value at the case's hour-1 print, with the
  effective print capped at 300,000 viewers: beyond that the model holds the
  shape of a 300k launch (peak ~1.3x hour 1, matching the biggest launches
  actually observed) instead of extrapolating to a flat day. GTA VI unlocks
  rolling at midnight local with the US still pending at hour 1, so its day
  cannot peak at hour 1 the way a simultaneous global PC unlock did.
- The spread is the pooled empirical residual quantiles of the large
  comparables only (hour-1 print >= 25,000), scaled by 0.8. The residual
  distribution is asymmetric -- downside bounded, upside long -- which the
  empirical quantiles capture and a normal spread would not.
- If too few comparable curves are usable, it falls back to the house
  persistence baseline.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

The kit's practice cases live in the (unpacked) kit's `input/` directory.
The program runs in ~0.1 s per case, is fully deterministic (two runs write
identical bytes), and needs no network.

## Verification (practice cases)

Practice answers were taken from SullyGnome's hourly averages, the same
source the cases were cut from, and scored with the rules' exact pinball loss
on the log scale:

| entry | loss | typical miss | 90% coverage |
|---|---|---|---|
| house baseline | 0.403 | 85.9% | 0.761 |
| this model | **0.186** | **28.4%** | **0.898** |

Per-case losses: p00 Marvel's Wolverine 0.184, p01 Red Dead Redemption 2
0.223, p02 God of War Ragnarok 0.149, p03 Marvel's Spider-Man 2 0.188.
Full method, tuning log, and edge-case tests are in BUILD-REPORT.md.

## Files

- `main.py` -- the entry (Python 3.13, stdlib only)
- `BUILD-REPORT.md` -- what was built, the model, and how it was verified
- `LICENSE` -- MIT

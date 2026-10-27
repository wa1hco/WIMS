# Spot scoring (DX cluster)

The live call roster is unchanged. It still uses `WEIGHTS` and
`WeightedFactorStrategy` in `src/wims/engine/scoring.py`. This page is the
separate score for the Operate **Spotted** list (design §2.15).

A spot is ranked only after it has already passed the filter: on a selected
band, still needed on that band and mode, a grid is known, the distance is
workable for that band, and the spot is younger than 15 minutes. A QSY does
not remove the spot.

Each term is `amount × weight`, rounded to 0.1. The line score is the sum,
rounded to 0.1. Hover the score to see the terms. A zero term is left off the
hover.

## Weights

| Name | Weight | Amount |
|------|--------|--------|
| `need_new` | 40 | 1 when the spot is a new multiplier or new place on that band and mode |
| `need_call` | 18 | 1 when the station is needed and is not a new multiplier |
| `need_unconfirmed` | 12 | 1 when the place is worked but not confirmed and the Goal still chases it |
| `recency` | 15 | 1 when the spot just arrived, 0 at 15 minutes, linear between |
| `spotters` | 10 | 1/3 for one spotter, 1 at three or more |
| `spotter_near` | 8 | 1 when the spotter is within 500 km, 0 at 2000 km and beyond. Omitted when the spotter’s grid is unknown |
| `distance` | 12 | 1 inside the sweet spot for that band, lower toward the edges, 0 outside (those spots are not listed) |
| `rover` | 15 | 1 for a `/R` call, or a call already heard as a rover |
| `qsy` | −8 | 1 when no live WSJT-X is on that band and mode. Setup can set the cost from 0 to 80; the weight is the negative of that cost |

Exactly one of `need_new`, `need_unconfirmed`, and `need_call` is used.
`need_new` wins, then `need_unconfirmed`.

The default QSY cost is 8. A new-grid spot that needs a QSY (40 − 8 = 32
before the workability terms) still beats an ordinary needed station that is
already on the radio (18 before those same terms). Cost 0 leaves the spot
with no penalty. Cost 80 can put a QSY spot under on-band spots. The cost is
saved with the other cluster choices.

## Worked example

One spotter within 500 km, the spot just arrived, distance inside the sweet
spot, not a rover:

| Spot | Terms | Score |
|------|--------|-------|
| New grid, on band | 40 + 15 + 3.3 + 8 + 12 | 78.3 |
| New grid, QSY | the same, minus 8 | 70.3 |
| Needed call, on band | 18 + 15 + 3.3 + 8 + 12 | 56.3 |

The new grid you would have to QSY for stays above the ordinary needed
station the radio is already on.

## Range from this station

Distance is from the grid WSJT-X reports (FN42EV at the home station). It is
not a hardcoded fallback: if no grid has arrived, the list stays empty and
the status says so. The numbers are “worth trying,” not the radio horizon.
MSK144 uses a meteor-scatter window: too close is dropped as well as too far.

| Band | Min km | Sweet spot km | Max km |
|------|--------|---------------|--------|
| 160 m | 0 | 80–1500 | 2500 |
| 80 m | 0 | 150–3000 | 5000 |
| 60 m | 0 | 150–2500 | 4000 |
| 40 m | 0 | 400–8000 | 12000 |
| 30 m | 0 | 800–12000 | 15000 |
| 20 m | 0 | 1000–16000 | 18000 |
| 17 m | 0 | 1000–16000 | 18000 |
| 15 m | 0 | 1500–16000 | 18000 |
| 12 m | 0 | 1500–14000 | 16000 |
| 10 m | 0 | 1500–14000 | 16000 |
| 6 m | 0 | 400–2500 | 6000 |
| 4 m | 0 | 400–1800 | 2500 |
| 2 m | 0 | 40–600 | 900 |
| 1.25 m | 0 | 30–400 | 700 |
| 70 cm | 0 | 20–300 | 500 |
| 33 cm | 0 | 10–150 | 300 |
| 23 cm | 0 | 5–120 | 250 |
| 13 cm | 0 | 5–80 | 150 |
| higher microwave | 0 | 5–80 | 150 |

6 m at 6000 km keeps a multi-hop sporadic-E path from FN42 to the Canary
Islands (IL18, about 5100 km) and the UK (about 5200 km). Central Europe
(about 6100 km) is past it. The sweet spot stays the single-hop window, so
those long spots score lower.

MSK144:

| Band | Min km | Sweet spot km | Max km |
|------|--------|---------------|--------|
| 6 m | 200 | 500–1800 | 2200 |
| 2 m | 200 | 400–1600 | 2200 |
| 1.25 m | 150 | 300–1200 | 1800 |
| 70 cm | 150 | 300–1000 | 1500 |

Below the sweet spot the distance term falls from 1 to 0.35 at the minimum.
Above it, the term falls from 1 at the sweet-spot edge to 0 at the maximum.

## Mode

A cluster line has no mode field. Inference, in order:

1. A word in the comment, longest match first. `FT8`, `FT4`, `MSK144`, `Q65`,
   `JT65`, `JT9`, `FST4`, `FST4W` (shown as FST4), `JS8`, `WSPR`, `PSK31`
   (shown as PSK), `RTTY`, `CW`, `FM`. `USB`, `LSB`, `SSB`, and `PHONE` show
   as SSB. `DATA` and `DIGI` show as data. `MSK` shows as MSK144. The match
   is a whole word, so `FM` does not match a grid `FN42` and `CW` does not
   match `CQ`.
2. The nearest known watering hole. FT8 is ±2.5 kHz of the usual dial
   (14.074, 28.074, 50.313, 144.174, and the other dials in
   `modes.py`). FT4 and JT65 are the narrower holes beside them. MSK144 is
   ±5 kHz of 50.260, 144.150, 222.150, and 432.150. Q65 is 50.275 and
   144.120. FM calling channels are 52.525, 146.520, and 446.000.
3. The US band plan for this station in FN42: below the data segment is CW,
   at and above the phone edge is SSB, and the gap is data. A watering hole
   is checked first, so 14.074 is FT8.
4. Otherwise the label is `other`.

Comment wins over the frequency. A comment that says CW on 28.074 is CW.

**On band** requires the same band and the same mode. An FT8 instance does
not cover a CW spot on that band.

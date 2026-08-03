# LiDAR heights — validation

Source: Contains Irish Public Sector Data (Geological Survey Ireland & the Office of Public Works) licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) licence.

- Footprints sampled: **21949**
- Read by LiDAR: **20364** (92.8%)
- Tagged and read, usable as ground truth: **3829**

## Calibration

Fitted on tagged buildings as `roof_85 = storey_m * levels + pitch_m`.

| Term | Value |
|---|---|
| Metres per storey | 2.93 |
| Roof pitch above eave | 1.25 m |
| Correlation | 0.763 |
| Buildings fitted | 3824 |

## Held-out accuracy

The calibration was re-fitted on 1913 tagged buildings and
scored on the 1916 it never saw, rounded to half storeys as
the renderer draws them. Error is predicted minus tagged storeys.

| Statistic | LiDAR | Flat default of 2 |
|---|---|---|
| Median error | +0.00 | +0.00 |
| Mean absolute error | 0.17 | 0.15 |
| Within half a storey | 95% | 88% |
| Within one storey | 98% | 98% |

Most tagged buildings really are 2 storeys, so the flat
default scores well on the bulk and the totals above understate the
difference. On the 225 test buildings that are *not*
2 storeys — exactly the ones a flat default gets wrong:

| Statistic | LiDAR | Flat default |
|---|---|---|
| Mean absolute error | 0.46 | 1.30 |
| Within half a storey | 82% | 0% |

Tagged buildings are a biased sample — mappers tag the tall and the
notable — so this flatters the anonymous terraces slightly.

## Tallest ridges found

| Building | Roof m | Ridge m | Pixels |
|---|---|---|---|
| Saint John's Cathedral | 50.5 | 56.4 | 28 |
| Riverpoint | 53.1 | 53.5 | 97 |
| Clayton Hotel | 48.2 | 50.8 | 354 |
| Riverpoint Apartments | 39.1 | 40.5 | 418 |
| way/317223432 | 28.9 | 38.4 | 145 |
| way/87989238 | 33.2 | 35.2 | 572 |
| way/284619208 | 32.6 | 33.7 | 102 |
| way/249627837 | 29.3 | 30.7 | 1285 |
| way/361354398 | 17.2 | 30.4 | 477 |
| way/249627836 | 28.0 | 29.7 | 1191 |
| way/1432784306 | 27.8 | 29.3 | 150 |
| way/107755248 | 24.9 | 28.9 | 971 |

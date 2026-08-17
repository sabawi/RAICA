# `compute` + `plot_data` — graduate-level test prompts (US government data)

Prompts for exercising RAICA's `compute()` and `plot_data()` tools with `@Ask` on NewX.
Each is self-contained: paste one paragraph as a single request.

**Created:** 2026-08-17 · **Against:** v1.0.0.304 + tool-prompt coverage (sections M and N)

---

## Before you run these — what was verified, and what constrains them

Every data source below was **fetched and column-parsed successfully** on 2026-08-17 before these
prompts were written, so none of them should fail on a bad URL or a mis-spelled column:

| source | rows | columns as parsed |
|---|---|---|
| USGS FDSN event query (H1 2026, M≥5.5) | 225 | `time`, `mag`, `depth`, `latitude`, `longitude`, `place`, … (22) |
| Treasury daily yield curve, 2026 | 157 | `Date`, `1 Mo`, `2 Mo`, `3 Mo`, `6 Mo`, `1 Yr`, `2 Yr`, `3 Yr`, `5 Yr`, `7 Yr`, `10 Yr`, `20 Yr`, `30 Yr` |
| FRED `DGS10` | 16,859 | `observation_date`, `DGS10` |
| FRED `T10Y2Y`, `FEDFUNDS`, `MORTGAGE30US`, `PAYEMS`, `GDPC1`, `VIXCLS`, `M2SL`, `HOUST`, `UNRATE`, `CPIAUCSL` | 318–13,100 | `observation_date`, `<SERIES_ID>` |

FRED CSV pattern: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>`

**Three real constraints these prompts are written to respect:**

1. **Missing values are real.** `DGS10` carries **719 NaNs** in 16,859 rows (FRED writes `.` for
   market holidays). `np.mean` returns `nan`; `np.nanmean` returns 5.8063. Several prompts below
   deliberately require the nan-aware family — that is a genuine analytical trap, not a gimmick.
2. **An expression is capped at 500 characters** and arrays at 200,000 elements.
3. **Only pure-maths numpy is available** — 98 functions. No `scipy`, no `np.linalg`, no
   `np.random`, no `np.fft`, and **no `skew`/`kurtosis`**: those must be built from moments, e.g.
   `np.mean(((x - np.mean(x)) / np.std(x)) ** 3)`. `np.polyfit`, `np.corrcoef`, `np.cov`,
   `np.gradient`, `np.histogram`, `np.percentile`, `np.cumsum`, `np.searchsorted` and the whole
   `nan*` family **are** available.

---

## 1. USGS earthquakes — Gutenberg–Richter b-value ⭐ *regression testcase*

Get the USGS earthquake catalog for the first half of 2026, magnitude 5.5 and above, from this exact URL: https://earthquake.usgs.gov/fdsnws/event/1/query?format=csv&starttime=2026-01-01&endtime=2026-06-30&minmagnitude=5.5 — compute the sample size, mean, median and sample standard deviation of the magnitudes, then measure the shape properly: report the skewness and excess kurtosis from the standardised moments, the 5th/25th/50th/75th/95th percentiles, and the interquartile range. Estimate the Gutenberg–Richter b-value by binning magnitudes at 0.1 intervals, taking the base-10 logarithm of the cumulative count at or above each bin, and fitting a straight line to that log-linear relationship; report the slope, the implied b-value and what it says about the relative frequency of large events. Plot the magnitude histogram with the fitted decay overlaid, and state in the caption which distribution family the measurements support and why. State every figure with the expression that produced it and the number of observations.

## 2. Treasury yield curve — term structure and inversion ⭐ *regression testcase*

Fetch the 2026 daily Treasury yield curve from https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026&page&_format=csv — compute, for the 3 Mo, 2 Yr, 10 Yr and 30 Yr tenors, the mean, standard deviation, minimum, maximum and peak-to-peak range of each. Then analyse the term structure: compute the 10Y−2Y and 30Y−3Mo spreads across the year, report the mean and the most negative value of each, count how many trading days each spread was inverted (below zero) and express that as a share of all observations. Compute the correlation matrix between the 3 Mo, 2 Yr, 10 Yr and 30 Yr series and say which tenors move together most tightly and which pair is least correlated. Produce two charts: the four yield series over time, and the 10Y−2Y spread with a zero reference line so inversions are visible. Quote each figure with its expression and n.

## 3. FRED DGS10 — six decades of the 10-year yield, with missing data

Fetch the full history of the 10-year Treasury constant-maturity yield from https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10 — this series contains missing observations for market holidays, so handle them explicitly and tell me how many there are. Compute the count of valid observations, the count of missing ones, and the nan-aware mean, median, standard deviation and 1st/99th percentiles. Compute the daily change series and report its standard deviation as a measure of realised volatility, the largest single-day rise and the largest single-day fall. Identify the all-time maximum and minimum yields and report their positions in the series. Then split the record at the halfway point, compute the mean and standard deviation of each half separately, and say plainly whether the level and the volatility of the second half differ from the first. Plot the full series and, separately, the distribution of daily changes. Report every figure with the expression used.

## 4. Inflation — CPI level to annualised rate

Fetch the Consumer Price Index for All Urban Consumers from https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL — the series is an index level, not a rate, so derive the inflation rate yourself: compute month-over-month log differences, annualise them, and report the mean, median and standard deviation of the annualised rate. Compute the year-over-year inflation rate by comparing each observation with the one twelve months earlier, and report its mean, its maximum and its minimum together with where in the series those extremes fall. Report the 10th and 90th percentiles of the year-over-year rate, and count how many months exceeded 5% annual inflation. Plot the CPI index level and the year-over-year inflation rate as two charts. Show the expression behind every number.

## 5. Phillips curve — unemployment against inflation ⭐ *regression testcase*

Fetch two series — the civilian unemployment rate from https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE and the Consumer Price Index from https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL — and test the Phillips-curve relationship on them. Compute descriptive statistics for the unemployment rate: mean, median, standard deviation, minimum, maximum and the 5th/95th percentiles. Derive year-over-year CPI inflation from the index. Align the two series over their common period, compute the Pearson correlation between unemployment and inflation, and fit a straight line to inflation as a function of unemployment, reporting the slope and intercept. State whether the sign of the slope supports the classical inverse relationship or contradicts it, and be explicit that a correlation on aggregate time-series data is not causal evidence. Plot unemployment and inflation over time on one chart, and a scatter of inflation against unemployment with the fitted line on another. Give the expression and n for every figure.

## 6. Yield-curve inversion as a recession signal

Fetch the 10-year minus 2-year Treasury spread from https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10Y2Y — compute the count of valid observations, the nan-aware mean, median and standard deviation, and the most negative value in the record. Count how many days the spread was below zero and express that as a percentage of all valid observations. Compute the daily change series and report its standard deviation, and identify the largest single-day move in each direction. Compute the 1st, 5th, 25th, 75th, 95th and 99th percentiles of the spread and comment on how asymmetric the distribution is by comparing the distance from the median to each tail. Plot the spread over time with a zero reference line, and plot its distribution as a histogram. Every figure must carry its expression and observation count.

## 7. Fed funds rate versus mortgage rates — transmission

Fetch the effective federal funds rate from https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS and the 30-year fixed mortgage average from https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US — compute mean, median, standard deviation and range for each. Over their overlapping period, compute the correlation between the two, and the mean spread of mortgage rates over the funds rate together with its standard deviation, minimum and maximum. Fit a line predicting the mortgage rate from the funds rate and report the slope — that is, how much a one-point move in policy has historically accompanied a move in mortgage pricing. Report the periods where the spread was widest and narrowest. Plot both series over time, and plot the spread separately. State each figure with its expression.

## 8. Employment — payrolls growth and its distribution

Fetch total non-farm payrolls from https://fred.stlouisfed.org/graph/fredgraph.csv?id=PAYEMS — the series is a level in thousands of jobs, so compute the month-over-month change yourself. Report the mean, median and standard deviation of monthly job changes, the largest monthly gain and the largest monthly loss, and the skewness of the change distribution from its standardised third moment. Count how many months showed job losses and express that as a share of all months. Compute the cumulative sum of changes over the most recent 120 months to give net jobs added over that decade. Report the 1st and 99th percentiles of monthly change and say how far the worst month sits below the 1st percentile in standard deviations. Plot the payrolls level and the monthly change distribution. Show every expression.

## 9. Market volatility — the VIX distribution

Fetch the CBOE volatility index from https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS — handle missing observations explicitly and report how many there are. Compute the nan-aware mean, median, standard deviation, minimum and maximum, and the 50th/75th/90th/95th/99th percentiles. Volatility indices are strongly right-skewed, so test that: compute the skewness from the standardised third moment, compare the mean against the median, and compute the same statistics on the natural logarithm of the series to show how much the transformation reduces the skew. Count the days above 30 and above 40 and express each as a share of valid observations. Plot the VIX level over time, and plot the distributions of the raw and log-transformed series so the effect of the transformation is visible. Report expressions and n throughout.

## 10. Housing starts — seasonality and cycle

Fetch US housing starts from https://fred.stlouisfed.org/graph/fredgraph.csv?id=HOUST — compute mean, median, standard deviation, minimum, maximum and the interquartile range. Compute the month-over-month percentage change series and report its mean, standard deviation and the 5th and 95th percentiles. Using the rate of change of the series, identify the steepest sustained decline and the steepest sustained expansion. Compute the correlation between housing starts and the 30-year mortgage rate from https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US over their common period, and report the sign and strength. Plot housing starts over time and a scatter of housing starts against mortgage rates. Every figure with its expression and n.

## 11. Money supply and inflation — the quantity theory

Fetch M2 money stock from https://fred.stlouisfed.org/graph/fredgraph.csv?id=M2SL and the CPI from https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL — compute year-over-year growth rates for both. Report mean, median and standard deviation of each growth series. Over the common period, compute the correlation between M2 growth and CPI inflation, both contemporaneously and with M2 growth shifted forward by twelve months, and say which alignment shows the stronger association. Fit a line of inflation on lagged money growth and report the slope. Be explicit about what this evidence can and cannot establish about causation. Plot both growth rates over time on one chart, and the lagged scatter with its fitted line on another. Give every expression.

## 12. Real GDP — growth, cycles and contractions

Fetch real GDP from https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDPC1 — the series is quarterly and in chained dollars. Compute the quarter-over-quarter growth rate, annualise it, and report the mean, median, standard deviation and range of annualised growth. Count the quarters of negative growth and express them as a share of all quarters; identify the deepest single-quarter contraction and the strongest expansion. Compute the skewness and excess kurtosis of the growth distribution from standardised moments and say what the tails imply about the frequency of severe contractions relative to a symmetric bell-shaped assumption. Compute the compound growth rate implied by the first and last observations. Plot real GDP over time and the distribution of annualised quarterly growth. Report each figure with its expression and n.

---

## My three regression testcases

Marked ⭐ above. Chosen because between them they cover every mechanism that broke, and each
fails loudly rather than subtly if a piece regresses:

**#1 USGS earthquakes** — the original reported failure, and the only one whose correct answers
I have independently verified: n=225, mean 5.8828, median 5.8, sample std 0.421845, max 7.8,
histogram counts `[75, 61, 40, 20, 8, 9, 2, 2, 2, 3, 2, 1]` at 12 bins. It exercises a single
fetched column, the reference mechanism, a multi-expression batch, `np.polyfit` on a log
transform, and one chart. **Any wrong number here is immediately detectable.**

**#2 Treasury yield curve** — the only prompt using a **multi-column** table (13 tenors), so it
tests column-name fidelity where spellings contain spaces (`10 Yr`, `1 Mo`). It requires arithmetic
*between* columns (spreads), a correlation matrix, conditional counting, and **two** charts. It is
the strongest test of the reference mechanism under realistic column naming.

**#3 Phillips curve** — the only prompt requiring **two separately fetched sources joined on a
common period**, which is where the `{"from": ["lookup_website#1", "lookup_website#2"]}` list form
matters. It also needs a derived series (YoY inflation from an index) feeding a `np.polyfit`
regression, and it asks for an explicit causal-inference caveat — so it tests analytical honesty,
not just arithmetic.

### What to check when running them

- **No `sandboxed_executor` for arithmetic.** If a script gets written, tool routing has regressed.
- **Every figure carries its expression and n.** A bare number is a fabrication signal.
- **Charts render and are accurate** — spot-check two plotted points against the reported stats.
- **NaN-bearing series report their missing count.** Silence there means the nan trap was missed.
- **If a calculation fails, the answer must say so and omit the figure**, never estimate it.

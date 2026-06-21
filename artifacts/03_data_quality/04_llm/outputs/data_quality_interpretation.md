# Stakeholder Summary  

The Formula 1 data warehouse is in very good shape overall – the automated quality checks gave an average overall score of **0.9999** across the ten core tables, and every table is flagged as “green”.  

**What’s working well**  
- Five tables ( * circuit, driver, grand_prix, season, team* ) have **perfect scores** on every dimension.  
- All referential‑integrity checks passed, so foreign‑key links (e.g., drivers to teams, laps to sessions) are intact.  

**Where attention is needed**  
- The **track_status** table shows the lowest overall score (0.9989). The issue is a modest number of duplicate rows (uniqueness score 0.9946).  
- The **result** table has a single completeness problem – a few rows are missing the required `driver_id` and `team_id`.  
- The **lap** table, while still green, contains the bulk of the remaining issues (60 issues). Most of these are **validity warnings** about tyre‑compound values, plus a large amount of missing performance data (lap times, sector times, speeds, tyre life).  

**Missing‑value highlights**  
- **Lap times** (`lap.lap_time_ms`) are missing in **5 370** rows (≈ 9 % of lap records) and are flagged as *red* (high‑severity).  
- **Tyre‑related fields** (`tyre_life`, `compound`) have several hundred missing values, also flagged as red.  
- Speed‑sensor columns (`speed_fl`, `speed_st`, etc.) contain many *explained* nulls (e.g., when a sensor was not active) but also a noticeable number of *suspicious* nulls.  

**Outlier highlights**  
- Automated outlier detection identified **5 213 strong‑consensus outliers**. The most affected metrics are:  
  - **Straight‑line speed (speed_st)** – 1 683 outliers  
  - **Front‑left wheel speed (speed_fl)** – 1 101 outliers  
  - **Lap time** – 488 outliers  

These outliers are not proven errors, but they represent unusual values that merit a human look‑over (e.g., possible timing glitches or sensor faults).

In short, the data are reliable for most reporting and analytics, but the **lap** table’s missing values and outliers, plus a few uniqueness and completeness gaps, should be examined before final analyses are published.

---

# Technical Summary  

| Table | Quality Dimension | Issue Count | Description (sample) |
|-------|-------------------|-------------|----------------------|
| **track_status** | Uniqueness | 9 | Duplicate rows detected (uniqueness = 0.9946). |
| **result** | Completeness | 1 | Row `result_id=180` missing required `driver_id` and `team_id`. |
| **lap** | Validity | 60 | Tyre‑compound values outside the allowed domain (e.g., rows `lap_id=16331‑16341`). |
| **lap** | Completeness | 0 (overall) | No completeness score loss, but many *missing* values flagged in the focused analysis (see below). |
| **All tables** | Referential Integrity | 0 | All foreign‑key checks passed. |

### Focused Missing‑Value Findings  

| Table / Column | Missing Count | Missing % | Classification | Information Area | Severity |
|----------------|--------------|----------|----------------|------------------|----------|
| `lap.lap_time_ms` | 5 370 | 8.8 % | **SUSPICIOUS_NULL** | LAP_TIME_INFORMATION | **red** |
| `lap.sector1_time_ms` | 4 255 | 6.9 % | SUSPICIOUS_NULL | SECTOR_INFORMATION | yellow |
| `lap.sector2_time_ms` | 337 | 0.55 % | SUSPICIOUS_NULL | SECTOR_INFORMATION | yellow |
| `lap.sector3_time_ms` | 1 142 (1 046 explained, 96 suspicious) | 1.86 % | MIXED (EXPLAINED + SUSPICIOUS) | SECTOR_INFORMATION | yellow |
| `lap.tyre_life` | 520 | 0.85 % | SUSPICIOUS_NULL | TYRE_INFORMATION | **red** |
| `lap.compound` | 334 | 0.55 % | SUSPICIOUS_NULL | TYRE_INFORMATION | **red** |
| `lap.speed_fl` | 5 536 (5 467 explained, 69 suspicious) | 9.0 % | MIXED | SPEED_INFORMATION | yellow |
| `lap.speed_st` | 410 (341 explained, 69 suspicious) | 0.67 % | MIXED | SPEED_INFORMATION | yellow |
| `lap.speed_i1` | 167 (98 explained, 69 suspicious) | 0.27 % | MIXED | SPEED_INFORMATION | yellow |
| `lap.speed_i2` | 301 (all suspicious) | 0.49 % | SUSPICIOUS_NULL | SPEED_INFORMATION | yellow |
| `result.time_ms` | 384 (all suspicious) | 21.8 % | SUSPICIOUS_NULL | RACE_CONTEXT_INFORMATION | yellow |
| `result.q1_ms`, `q2_ms`, `q3_ms` | 12, 10, 11 (all suspicious) | ≤ 0.7 % | SUSPICIOUS_NULL | QUALIFYING_INFORMATION | **red** |
| `result.position` | 3 (suspicious) | 0.17 % | SUSPICIOUS_NULL | CLASSIFICATION_INFORMATION | **red** |
| `result.driver_id`, `team_id` | missing in row `result_id=180` (yellow) | – | – | – | yellow |

*Overall missing‑value totals*: 18 794 nulls, of which 11 842 are flagged as **suspicious** (potential data‑quality concerns) and 6 952 as **explained** (e.g., sensor not present).

### Focused Outlier Detection  

- **Total tested values**: 239 175 (across all lap‑related metrics).  
- **Strong‑consensus outliers** (both IQR and Modified‑Z flagged): 5 213 (≈ 2.2 % of tested values).  
- **Metric‑wise strong‑consensus counts**:  

| Metric | Strong‑Consensus Outliers |
|--------|---------------------------|
| `speed_st` | 1 683 |
| `speed_fl` | 1 101 |
| `lap_time_ms` | 488 |
| `speed_i1` | 458 |
| `sector2_time_ms` | 420 |
| `sector1_time_ms` | 396 |
| `speed_i2` | 344 |
| `sector3_time_ms` | 323 |

- The top five sessions (by outlier count) are sessions 26, 8, 74, 84, 38 – each showing > 150 outliers for a single speed metric.  
- Sample strong‑consensus outliers (e.g., `lap_id=1244` with `lap_time_ms = 109 275 ms`) exceed the IQR upper bound and have Modified‑Z scores > 8, indicating values far from the typical range for that session.

These outliers are **not automatically errors** but represent data points that deviate strongly from the session‑specific distribution and should be inspected.

---

# Suggested Cleaning Priorities  

1. **Lap‑time completeness (red) – `lap.lap_time_ms`**  
   - 5 370 rows lack a lap‑time value. Verify whether the lap was not recorded (e.g., pit‑stop, aborted lap) or if the value was dropped during ingestion.  

2. **Tyre‑related missing data (red) – `lap.tyre_life` & `lap.compound`**  
   - Hundreds of rows have null tyre‑life or compound. Check source logs for tyre‑change events; confirm that missingness aligns with sessions where tyre data were not captured.  

3. **Validity of tyre‑compound domain (60 warnings)**  
   - Rows flagged as “compound must belong to the expected tyre compound domain”. Review the list of allowed compounds and compare against the offending values; they may be misspellings or outdated codes.  

4. **Duplicate rows in `track_status` (uniqueness)**  
   - Nine duplicate entries reduce the uniqueness score. Identify the key columns (likely `session_id` + status timestamp) and decide whether duplicates are true repeats or need consolidation.  

5. **Result table completeness – missing `driver_id` / `team_id`**  
   - Row `result_id=180` is missing required foreign keys. Cross‑reference with driver/team master tables to fill in or confirm that the result belongs to a non‑participating entry (e.g., DNS).  

6. **Result time missing (`result.time_ms`) – 384 yellow flags**  
   - Missing race‑time values in many result rows. Determine if the race was not completed, if the driver retired, or if the data extraction failed.  

7. **Qualifying‑session missing times (`result.q1_ms`, `q2_ms`, `q3_ms`) – red flags**  
   - Small numbers but high severity; verify whether the driver failed to set a time in that qualifying segment.  

8. **Speed‑sensor missing values (mixed explained/suspicious)**  
   - Columns `speed_fl`, `speed_st`, `speed_i1`, `speed_i2` contain a mix of explained nulls (sensor off) and suspicious nulls. Confirm sensor‑availability metadata; flag any unexpected gaps for further investigation.  

9. **Strong‑consensus outliers (especially `speed_st`, `speed_fl`, `lap_time_ms`)**  
   - Review the top outlier sessions (e.g., session 26, metric `speed_fl`) and the sample outlier rows. Check for data‑capture glitches, timing‑system resets, or genuine extreme performance (e.g., red‑flag laps).  

10. **Document any business‑rule exceptions**  
    - For all the above, capture the rationale for any retained nulls or outliers (e.g., “lap aborted due to crash”, “tyre sensor offline”). This documentation will support downstream analysts and future DQA cycles.  

*All suggested actions are **human‑review tasks**; automated deletion or correction is not recommended without domain confirmation.*
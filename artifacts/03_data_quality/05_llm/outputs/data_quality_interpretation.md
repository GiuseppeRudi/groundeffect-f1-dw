## Stakeholder Summary  

The Formula 1 data warehouse is in **very good overall shape**. Across the ten core tables the average quality score is **0.9999**, and every table is flagged “green”.  

**What’s working best**  
- **Circuit, Driver, Grand Prix, Season, Team** – each scores a perfect 1.0 with **no issues** at all. These tables can be trusted for reporting and analytics without further inspection.  

**Where the data are weakest**  
- **Track Status** – overall score 0.9989 (the lowest of the set). The only problem is **uniqueness**: 9 duplicate rows were found, lowering the uniqueness score to 0.9946.  
- **Lap** – overall score 0.99997 but **60 validity issues** were detected (all related to tyre‑compound values).  
- **Result** – overall score 0.99993 with a single **completeness issue** (missing required driver/team identifiers on one row) and a larger pattern of missing race‑time values.  

**Missing‑value signals that matter**  
- In the **Lap** table, the columns that should hold core timing information are incomplete:  
  - `lap_time_ms` – 5 368 suspicious nulls (≈ 8.8 % of rows)  
  - `sector1_time_ms` – 4 253 suspicious nulls (≈ 7 %)  
  - `tyre_life` – 520 suspicious nulls (≈ 0.85 %)  
  - `compound` – 334 suspicious nulls (≈ 0.55 %)  
  - Several speed columns contain a mix of explained and suspicious nulls (e.g., `speed_fl` has 5 534 nulls, 5 467 of which are explained).  

- In the **Result** table, the race‑time column `time_ms` is missing in **384 rows** (≈ 22 % of results) and a handful of qualifying‑time columns (`q1_ms`, `q2_ms`, `q3_ms`) have small but non‑trivial gaps.  

**Outlier signals that matter**  
- The outlier analysis flagged **5 213 strong‑consensus outliers** (≈ 2 % of all numeric measurements).  
- The metrics with the most strong outliers are **speed at the straight (`speed_st`) – 1 683 flags** and **speed on the front‑left (`speed_fl`) – 1 101 flags**.  
- Lap‑time itself also shows a notable number of strong outliers (488 flags).  
- Certain sessions (e.g., session 26, 8, 74, 84) contain a high concentration of outliers for the speed metrics, suggesting possible sensor or recording anomalies for those events.  

Overall, the data are reliable, but the **Lap** and **Result** tables contain the bulk of the missing‑value and outlier concerns that should be examined before downstream analytics.

---

## Technical Summary  

| Table | Quality Dimension | Issue Count | Description / Sample |
|-------|-------------------|-------------|-----------------------|
| **track_status** | Uniqueness | 9 | Duplicate rows detected; overall uniqueness = 0.9946. |
| **lap** | Validity | 60 | Tyre‑compound values fall outside the allowed domain (e.g., `lap_id=16330` … `lap_id=16358`). |
| **lap** | Completeness (Missing Values) | 18 356 total missing entries (≈ 30 % of lap rows) – broken down by information area: <br>• LAP_TIME_INFORMATION: 5 368 suspicious nulls (`lap_time_ms`). <br>• SECTOR_INFORMATION: 4 253 suspicious nulls (`sector1_time_ms`) + 335 suspicious nulls (`sector2_time_ms`) + 94 suspicious + 1 046 explained nulls (`sector3_time_ms`). <br>• TYRE_INFORMATION: 520 suspicious nulls (`tyre_life`) + 334 suspicious nulls (`compound`). <br>• SPEED_INFORMATION: 299 suspicious nulls (`speed_i2`) + 165 suspicious nulls (`speed_i1`) + 67 suspicious nulls each for `speed_fl`, `speed_i1`, `speed_st` plus many explained nulls (e.g., `speed_fl` 5 467 explained). |
| **result** | Completeness | 1 (structural) + 384 missing `time_ms` + 33 missing qualifying times + 3 missing `position` | Sample: `result_id=180` missing `driver_id` and `team_id`; many rows missing `time_ms` in race sessions (e.g., `result_id=32`). |
| **result** | Missing Values (by area) | 422 total missing entries (≈ 24 % of result rows) – all flagged as suspicious. Main areas: RACE_CONTEXT_INFORMATION (384), QUALIFYING_INFORMATION (33), CLASSIFICATION_INFORMATION (3). |
| **lap** | Outliers (Strong Consensus) | 5 213 flags across metrics. Top metrics: <br>• `speed_st` – 1 683 flags <br>• `speed_fl` – 1 101 flags <br>• `lap_time_ms` – 488 flags <br>• `speed_i1` – 458 flags <br>• `sector2_time_ms` – 420 flags |
| **lap** | Outlier Sessions (high concentration) | Session 26 (`speed_fl` 208 consensus outliers), Session 8 (`speed_st` 174), Session 74 (`speed_fl` 163), Session 84 (`speed_st` 155), etc. |
| **lap** | Sample Strong‑Consensus Outlier | `lap_id=1244` (session 2) – `lap_time_ms` = 109 275 ms, flagged by both IQR and Modified‑Z (consensus = 2). Similar patterns appear for many laps in session 6, indicating systematic timing anomalies. |

**Dimension‑level health** (from the DQA scorecard):  

- **Completeness** – 10 checks, all green; only 1 issue (the missing driver/team in `result`).  
- **Uniqueness** – 16 checks, all green; 9 duplicate rows in `track_status`.  
- **Validity** – 34 checks, all green; 60 tyre‑compound violations in `lap`.  
- **Consistency, Referential Integrity, Accuracy, Timeliness** – no failures reported.  

No referential‑integrity violations were found across the model.

---

## Suggested Cleaning Priorities  

> **Important:** All recommendations are **human‑review tasks**. Automated deletion or correction is **not** advised without domain verification.

1. **Validate and resolve tyre‑compound entries in the `lap` table** (60 rows). Confirm the correct compound codes for the affected laps and update the records accordingly.  

2. **Investigate duplicate rows in `track_status`** (9 rows). Determine whether they represent genuine distinct events or erroneous repeats, and decide whether to merge or remove duplicates.  

3. **Address structural missing values in `result`**:  
   - Fill in the missing `driver_id` and `team_id` for `result_id=180` (and any similar rows).  
   - Review the 384 rows missing `time_ms` (race‑context) to verify whether the race was not completed, data were not recorded, or a different column should be used.  

4. **Prioritize the “suspicious null” patterns in `lap`**:  
   - `lap_time_ms` (5 368 rows) – check if laps were not timed (e.g., due to red‑flag periods) or if data ingestion failed.  
   - `tyre_life` (520 rows) and `compound` (334 rows) – verify tyre‑usage logs; missing values may indicate incomplete pit‑stop records.  

5. **Review speed‑measurement gaps**:  
   - `speed_fl` (5 467 explained nulls) – these are likely legitimate “no‑speed” periods (e.g., pit‑lane), but confirm the explanation logic.  
   - The smaller set of **suspicious** speed nulls (67 rows each for `speed_fl`, `speed_i1`, `speed_st`) should be examined for sensor drop‑outs.  

6. **Examine strong‑consensus outliers** in the most affected metrics:  
   - **`speed_st`** (1 683 flags) and **`speed_fl`** (1 101 flags) – especially in sessions 26, 8, 74, 84. Verify telemetry calibration, session type (practice vs race), and any known incidents (e.g., safety car, rain).  
   - **`lap_time_ms`** (488 flags) – many outliers cluster in session 6; check for timing system resets or data‑export errors.  

7. **Document any business‑rule exceptions** uncovered during the above reviews (e.g., intentional missing values during qualifying eliminations) so that future DQA runs can classify them as “explained” rather than “suspicious”.  

8. **Re‑run the DQA after remediation** to confirm that the overall score improves and that the issue counts for the affected tables drop to zero.  

By following this prioritized, human‑centric checklist, the data engineering team can bring the few remaining weak spots to the same high standard as the rest of the warehouse, ensuring trustworthy analytics for all Formula 1 stakeholders.
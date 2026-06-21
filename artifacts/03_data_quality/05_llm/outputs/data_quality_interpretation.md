# Stakeholder Summary  

The Formula 1 data warehouse is in very good shape overall – the average quality score across the ten core tables is **0.9999** and every table is flagged “green”.  Most dimensions (completeness, uniqueness, validity, consistency, referential integrity) score at or near 100 %.  

**Where the data are strongest**  
- **Circuit, Driver, Grand Prix, Season, Team** – each of these tables has a perfect score (1.0) and no recorded issues.  

**Where the data are weakest**  
- **Track Status** – the lowest overall score (0.9989).  The only dimension that falls short is **uniqueness** (0.9946), with nine duplicate‑key issues.  
- **Result** – a single completeness problem (missing driver / team identifiers for one row).  
- **Lap** – the largest number of issues (60) concentrated in **validity** (compound values) and a substantial amount of **missing information**.  

**Missing‑value signals that change the picture**  
- Across the warehouse **18 778** fields are null.  About **63 %** of these are flagged as *suspicious* (potential data‑entry gaps) and the rest are *explained* (e.g., not applicable for a particular session).  
- The biggest “information‑area” gaps are in **speed data** (6 406 nulls), **sector times** (5 728 nulls) and **lap‑time data** (5 368 nulls).  
- The most critical missing‑value patterns are:  
  - **lap.lap_time_ms** – 5 368 red‑severity nulls (race‑lap times missing).  
  - **lap.tyre_life** – 520 red‑severity nulls.  
  - **lap.compound** – 334 red‑severity nulls (tyre‑compound not recorded).  

**Outlier signals that change the picture**  
- Outlier detection flagged **9 254** metric values as anomalous; **5 213** of these are “strong consensus” outliers (both IQR and Modified‑Z tests agree).  
- The metrics with the most strong‑consensus outliers are:  
  1. **speed_st** (1 683 flags)  
  2. **speed_fl** (1 101 flags)  
  3. **lap_time_ms** (488 flags)  
  4. **speed_i1** (458 flags)  
- Certain sessions generate a high concentration of outliers (e.g., session 26 for `speed_fl`, session 8 for `speed_st`).  

Overall, the data are reliable, but a focused review of the few tables and columns listed above will tighten the warehouse for downstream analytics.

---

# Technical Summary  

| Table | Quality Dimension(s) | Issue Count | Detail |
|-------|----------------------|-------------|--------|
| **track_status** | Uniqueness (0.9946) | 9 | Duplicate key values detected; all other dimensions score 1.0. |
| **result** | Completeness (0.9997) | 1 | Row `result_id=180` missing required `driver_id` and `team_id`. |
| **lap** | Validity (0.99986) | 60 | Invalid `compound` values (tyre‑compound domain) for rows `lap_id=16330`‑`16358`. |
| **lap** | Completeness (1.0) | – | No completeness checks failed, but many **missing values** (see below). |
| **All other tables** | – | 0 | Perfect scores; no recorded issues. |

### Missing‑value summary (by column)

| Table | Column | Total rows | Missing | % Missing | Missing class | Information area | Severity |
|-------|--------|------------|---------|----------|---------------|------------------|----------|
| **lap** | `lap_time_ms` | 61 205 | 5 368 | 8.77 % | SUSPICIOUS_NULL | LAP_TIME_INFORMATION | red |
| **lap** | `sector1_time_ms` | 61 205 | 4 253 | 6.95 % | SUSPICIOUS_NULL | SECTOR_INFORMATION | yellow |
| **lap** | `tyre_life` | 61 205 | 520 | 0.85 % | SUSPICIOUS_NULL | TYRE_INFORMATION | red |
| **lap** | `compound` | 61 205 | 334 | 0.55 % | SUSPICIOUS_NULL | TYRE_INFORMATION | red |
| **lap** | `sector2_time_ms` | 61 205 | 335 | 0.55 % | SUSPICIOUS_NULL | SECTOR_INFORMATION | yellow |
| **lap** | `speed_i2` | 61 205 | 299 | 0.49 % | SUSPICIOUS_NULL | SPEED_INFORMATION | yellow |
| **lap** | `sector3_time_ms` | 61 205 | 1 140 | 1.86 % | EXPLAINED_NULL (1 046) / SUSPICIOUS_NULL (94) | SECTOR_INFORMATION | mixed |
| **lap** | `speed_fl` | 61 205 | 5 534 | 9.04 % | EXPLAINED_NULL (5 467) / SUSPICIOUS_NULL (67) | SPEED_INFORMATION | mixed |
| **lap** | `speed_st` | 61 205 | 408 | 0.67 % | EXPLAINED_NULL (341) / SUSPICIOUS_NULL (67) | SPEED_INFORMATION | mixed |
| **lap** | `speed_i1` | 61 205 | 165 | 0.27 % | EXPLAINED_NULL (98) / SUSPICIOUS_NULL (67) | SPEED_INFORMATION | mixed |
| **result** | `time_ms` | 1 760 | 384 | 21.82 % | SUSPICIOUS_NULL | RACE_CONTEXT_INFORMATION | yellow |
| **result** | `q1_ms` | 1 760 | 12 | 0.68 % | SUSPICIOUS_NULL | QUALIFYING_INFORMATION | red |
| **result** | `q2_ms` | 1 760 | 10 | 0.57 % | SUSPICIOUS_NULL | QUALIFYING_INFORMATION | red |
| **result** | `q3_ms` | 1 760 | 11 | 0.63 % | SUSPICIOUS_NULL | QUALIFYING_INFORMATION | red |
| **result** | `position` | 1 760 | 3 | 0.17 % | SUSPICIOUS_NULL | CLASSIFICATION_INFORMATION | red |
| **result** | `grid_position` | 1 760 | 2 | 0.11 % | SUSPICIOUS_NULL | RACE_CONTEXT_INFORMATION | yellow |

*Totals*: 18 778 missing values → 11 826 yellow‑severity, 6 258 red‑severity.  

### Outlier detection summary  

| Metric | Tested values | Strong‑consensus outliers | Weak anomalies |
|--------|---------------|---------------------------|----------------|
| `speed_st` | 29 944 | **1 683** | 2 398 |
| `speed_fl` | 29 944 | **1 101** | 1 377 |
| `lap_time_ms` | 29 944 | **488** | 1 053 |
| `speed_i1` | 29 944 | **458** | 1 236 |
| `sector2_time_ms` | 29 941 | **420** | 1 176 |
| `sector1_time_ms` | 29 572 | **396** | 1 246 |
| `speed_i2` | 29 944 | **344** | 1 034 |
| `sector3_time_ms` | 29 942 | **323** | 1 023 |

*Top sessions by consensus outliers* (selected):  

| Session | Metric | Tested | Consensus outliers |
|---------|--------|--------|--------------------|
| 26 | `speed_fl` | 1 279 | 208 |
| 8  | `speed_st` | 1 110 | 174 |
| 74 | `speed_fl` | 1 069 | 163 |
| 84 | `speed_st` | 1 298 | 155 |
| 38 | `speed_fl` | 1 130 | 149 |
| 52 | `speed_st` |   964 | 114 |
| 6  | `speed_st` | 1 105 | 82 |
| 26 | `speed_i1` | 1 279 | 39 |
| 6  | `lap_time_ms` | 1 105 | 41 |
| 6  | `lap_time_ms` (strong) – 30+ individual rows flagged (e.g., lap_id 1244, 3088, 3094…) with modified‑Z scores > 5. |

The outlier analysis shows that speed‑related columns (`speed_st`, `speed_fl`) dominate the consensus‑outlier count, and that several sessions contain a high proportion of anomalous lap‑time values.

---

# Suggested Cleaning Priorities  

1. **Validate and de‑duplicate `track_status` keys** – review the nine rows flagged for uniqueness violations; confirm whether they represent true distinct status records or accidental duplicates.  

2. **Investigate `lap.compound` validity** – 60 rows have compounds outside the expected domain.  Verify the correct tyre‑compound codes for those laps and correct or annotate them.  

3. **Address critical missing lap‑time information** – 5 368 red‑severity nulls in `lap.lap_time_ms`.  Determine if these laps belong to sessions where lap time is not recorded (e.g., pit‑in/out, safety‑car laps) and either fill with appropriate placeholders or flag them for exclusion from time‑based analyses.  

4. **Review missing tyre data** – `lap.tyre_life` (520 red) and `lap.compound` (334 red) nulls.  Cross‑check with `track_status` and `weather` tables to see if tyre data were unavailable for certain sessions; consider imputing from team‑level tyre strategies if appropriate.  

5. **Examine missing speed measurements** – 6 406 speed‑information nulls (mostly explained, but 67 + 67 + 67 + 67 + 67 + 67 + 67 + 67 + 67 = 603 suspicious across `speed_fl`, `speed_st`, `speed_i1`, `speed_i2`).  Verify sensor coverage for the affected laps; if data are truly missing, decide whether to exclude those laps from speed‑based KPIs.  

6. **Resolve `result` completeness issue** – row `result_id=180` lacks `driver_id` and `team_id`.  Confirm the correct driver/team and update; if the race was a non‑participation entry, annotate accordingly.  

7. **Prioritize sessions with high outlier concentrations** – especially sessions 26, 8, 74, 84, 38 for `speed_fl`/`speed_st`.  For each, sample the flagged rows, check for data‑capture errors (e.g., sensor glitches) or genuine extreme performance (e.g., red‑flag laps).  

8. **Inspect strong‑consensus lap‑time outliers** – the 488 `lap_time_ms` outliers (e.g., lap_id 1244, 3088, 3094…) have modified‑Z scores > 5.  Review the corresponding lap videos or telemetry to decide if they are data errors, pit‑stop laps, or legitimate unusually fast/slow laps.  

9. **Document any business‑rule exceptions** – where missing or outlier values are justified (e.g., qualifying‑only sessions, safety‑car periods), capture the rationale in metadata so downstream users understand the context.  

10. **Perform a targeted re‑run of the DQA after remediation** – once the above items are reviewed and corrected (or documented), re‑execute the quality checks to confirm that scores improve and that no new issues are introduced.  

> **Note:** All the steps above are recommendations for **human review**.  Automated deletion or modification of records should only occur after a data steward validates each case.  The LLM output is a summary of the detected signals; final decisions must be made by the project team.
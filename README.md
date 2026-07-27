<p align="center">
  <img src="docs/readme_assets/ground_effect.jpg" alt="Ground Effect Formula 1 project" width="76%">
</p>

<h1 align="center">Ground Effect — Formula 1 Data Warehouse</h1>

<p align="center">
  <strong>An end-to-end Formula 1 analytics engineering project.</strong><br>
  From FastF1 data to a quality-controlled PostgreSQL warehouse and decision-ready Tableau dashboards.
</p>

<p align="center">
  <img alt="Python 3.11" src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-Data%20Warehouse-4169E1?logo=postgresql&logoColor=white">
  <img alt="FastF1" src="https://img.shields.io/badge/Data-FastF1-E10600">
  <img alt="Tableau" src="https://img.shields.io/badge/Visualization-Tableau-E97627?logo=tableau&logoColor=white">
  <img alt="Reproducible pipeline" src="https://img.shields.io/badge/Pipeline-Reproducible-2E8B57">
  <img alt="Feature complete" src="https://img.shields.io/badge/Status-Feature%20Complete-4C566A">
</p>

> [!NOTE]
> **Case study.** Ground Effect was developed in a university setting and delivered as a professional, end-to-end data engineering project. The repository prioritizes reproducibility, traceable data-quality decisions, dimensional modelling, and clear technical documentation.

## Overview

Ground Effect transforms heterogeneous Formula 1 timing, result, weather, and
track-status data into a consistent analytical platform. The project covers the
complete data lifecycle: extraction, source reconciliation, quality assessment,
cleaning, dimensional modelling, PostgreSQL loading, validation, and
business-intelligence delivery.

The solution is organized as a reproducible, configuration-driven pipeline rather
than a collection of isolated notebooks. Each stage produces auditable artifacts and
can run independently or through a fail-fast orchestration entry point.

The warehouse supports two complementary perspectives:

- **Lap Performance** — lap time, sectors, speed, tyre condition, weather, track status, and data-quality context.
- **Session Result** — race and qualifying results, grid position, outcome, gap to leader, session weather, and result-quality context.

## Project at a glance

| Capability | Implementation |
|---|---|
| **Sources** | FastF1 and Ergast/Jolpica, enriched with controlled domain tables |
| **Pipeline** | Python, pandas, NumPy, YAML configuration, and fail-fast orchestration |
| **Storage** | PostgreSQL layers for reconciled, cleaned, and warehouse data |
| **Quality** | Deterministic checks, contextual missing-value analysis, outlier consensus, and traceable cleaning actions |
| **Model** | Two fact tables and shared conformed dimensions |
| **Delivery** | Warehouse CSV exports and analytical dashboards for Tableau |

## Engineering highlights

- **End-to-end ownership:** ingestion, database design, pipeline orchestration,
  validation, and BI delivery are managed within one coherent workflow.
- **Layered architecture:** reconciled, cleaned, and dimensional warehouse layers
  separate source harmonization, data remediation, and analytics concerns.
- **Domain-aware quality controls:** missing values and outliers are evaluated in
  Formula 1 context instead of being removed through indiscriminate generic rules.
- **Traceable transformations:** intermediate outputs and validation reports make
  data-quality decisions reviewable and reproducible.
- **Production-style execution:** configuration-driven stages, deterministic SQL
  builds, and fail-fast checks support repeatable runs and easier diagnosis.

## The data journey

<p align="center">
  <img src="docs/readme_assets/pipeline_roadmap.png" alt="Ground Effect data pipeline roadmap" width="92%">
</p>

The pipeline follows five logical stages:

1. **Acquire and reconcile** Formula 1 source data into ten normalized relational tables.
2. **Assess quality** through completeness, uniqueness, validity, consistency, plausibility, and referential-integrity checks.
3. **Clean and document** invalid, missing, or suspicious values using explicit rules and an audit log.
4. **Build the warehouse** by deriving analytical categories and loading the two star-schema facts.
5. **Publish for analysis** by exporting warehouse tables as Tableau-ready CSV files.

## From reconciled data to the warehouse

The reconciled database keeps source entities normalized, preserving their natural relationships and making quality controls transparent.

<p align="center">
  <img src="docs/readme_assets/reconciled_schema.png" alt="Logical schema of the reconciled Formula 1 database" width="88%">
</p>

The analytical layer then reorganizes the cleaned data around **Lap Performance** and **Session Result**. Shared dimensions make driver, team, Grand Prix, circuit, weather, outcome, tyre, and quality analyses consistent across both facts.

<p align="center">
  <img src="docs/readme_assets/integrated_star_schema.png" alt="Integrated Ground Effect star schema" width="96%">
</p>

## Data quality is part of the model

Quality is not treated as a final check. It is measured before cleaning, recorded at row level, and carried into dedicated warehouse dimensions. This allows analysts to filter unreliable sector, speed, tyre, weather, track-status, qualifying, or race-context information without discarding every affected record.

### Expected vs unexpected nulls

Missing values are interpreted according to their Formula 1 context. **Explained nulls** are expected consequences of qualifying progression, pit activity, or non-applicable attributes; **suspicious nulls** identify information that should normally be available and therefore requires a quality flag or cleaning decision.

<p align="center">
  <img src="docs/readme_assets/expected_vs_unexpected_nulls.png" alt="Expected versus unexpected missing values" width="92%">
</p>

### Outlier consensus score

Outliers are evaluated with both IQR and Modified Z-score. Their agreement produces a consensus score, separating weak statistical signals from stronger anomalies that require a deterministic cleaning or quality-flag decision.

<p align="center">
  <img src="docs/readme_assets/outlier_consensus_score.png" alt="Outlier consensus score by lap metric" width="92%">
</p>

## Quick start

### Prerequisites

- Python 3.11
- Conda
- PostgreSQL
- Tableau Desktop or Tableau Public to open the packaged dashboards

### 1. Create the environment

From the project root:

```bash
conda env create -f environment.yml
conda activate ground_effect-dw
```

### 2. Configure PostgreSQL

Create a PostgreSQL database named `ground_effect_dw`, then expose its SQLAlchemy connection URL. For example:

```powershell
$env:GROUND_EFFECT_DW_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@localhost:5432/ground_effect_dw"
```

On macOS or Linux, use `export GROUND_EFFECT_DW_DATABASE_URL="..."` instead.

### 3. Run the complete pipeline

```bash
python pipeline/run_pipeline.py
```

The runner executes the enabled stages in order and stops immediately if one fails. Its behaviour and enabled steps are defined in `pipeline/pipeline_steps.yaml`.

> **Note:** the complete run rebuilds the project data layers and warehouse outputs. Make sure PostgreSQL is running and the connection URL points to the intended local database.

## Main outputs

| Location | Content |
|---|---|
| `data/reconciled/` | Normalized CSV representation of the source domain |
| `data/cleaned/` | Cleaned records enriched with quality flags |
| `data/warehouse/` | Physical fact and dimension CSV files |
| `artifacts/03_data_quality/` | Scorecards, issue files, missing-value and outlier evidence |
| `artifacts/04_data_cleaning/` | Cleaning log, summaries, rejected rows, and before/after comparison |
| `visualization/` | Tableau project material |

## Documentation

- [Final Report](docs/final_report/report.pdf) — complete methodology, modelling decisions, and implementation results.
- [Detailed technical reports](docs/detailed_reports/) — focused documents for re-engineering, dimensional design, data quality, cleaning, type validation, and outlier analysis.
- [Pipeline source](pipeline/) — reproducible implementation of the complete workflow.

These materials document the architecture, design rationale, quality criteria,
operational execution, and analytical delivery in greater detail.

## Tableau dashboard gallery

The Tableau layer turns the warehouse into two complementary views of championship and race-weekend performance.

### Competitive Balance

This dashboard compares the leading teams across 2021 and 2022 through cumulative points gaps, final standings, race wins, and pole positions.

<p align="center">
  <img src="docs/readme_assets/tableau/competitive_balance.png" alt="Competitive Balance Tableau dashboard" width="98%">
</p>

### Qualifying vs Race

This view connects qualifying position with race performance, comparing conversion, consistency, and round-by-round gaps for Ferrari, Mercedes, and Red Bull.

<p align="center">
  <img src="docs/readme_assets/tableau/qualifying_vs_race.png" alt="Qualifying versus Race Tableau dashboard" width="98%">
</p>

## Project status

> [!IMPORTANT]
> **Feature-complete and intentionally archived.** Ground Effect is the final version
> of a university Data Warehouse project completed to a professional portfolio
> standard. The repository is preserved as a documented, reproducible reference
> implementation rather than an actively evolving product.

<p align="center">
  <strong>Built to make Formula 1 data explainable, reproducible, and ready for visual analysis.</strong><br>
  Data engineering, quality, and analytics across the full race weekend.
</p>

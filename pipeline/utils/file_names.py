from __future__ import annotations

from pathlib import Path


# ============================================================
# PROJECT ROOT
# ============================================================


# parents[0] = utils
# parents[1] = pipeline
# parents[2] = root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ============================================================
# MAIN PROJECT DIRECTORIES
# ============================================================

PIPELINE_DIR = PROJECT_ROOT / "pipeline"

DATA_DIR = PROJECT_ROOT / "data"

ARTIFACT_DIR = PROJECT_ROOT / "artifacts"

DATABASE_DIR  = PROJECT_ROOT / "database"

VISUALIZATION_DIR  = PROJECT_ROOT / "visualization"

DOCS_DIR  = PROJECT_ROOT / "docs"

CACHE_DIR = PROJECT_ROOT / "cache"


# ============================================================
# DATA DIRECTORIES
# ============================================================

RAW_DATA_DIR = DATA_DIR / "raw"

RECONCILED_DATA_DIR = DATA_DIR / "reconciled"

CLEANED_DATA_DIR = DATA_DIR / "cleaned"

WAREHOUSE_DATA_DIR = DATA_DIR / "warehouse"

EXTERNAL_DATA_DIR = DATA_DIR / "external"


# ============================================================
# ARTIFACT DIRECTORIES
# ============================================================

EXTRACTION_OUTPUT_DIR = ARTIFACT_DIR / "01_extraction_reengineering"

LOAD_RECONCILED_OUTPUT_DIR = ARTIFACT_DIR / "02_load_reconciled_db"


DATA_QUALITY_OUTPUT_DIR = ARTIFACT_DIR / "03_data_quality"

### 
GENERAL_DQA_OUTPUT_DIR = DATA_QUALITY_OUTPUT_DIR / "01_dqa"


######

SCORECARDS_DIR_NAME = "scorecards"
ISSUES_DIR_NAME = "issues"
ISSUES_BY_TABLE_DIR_NAME = "by_table"
VISUALIZATIONS_DIR_NAME = "visualizations"

################

HTML_DIR_NAME = "html"
TABLES_DIR_NAME = "tables"

################

######

LLM_OUTPUT_DIR = DATA_QUALITY_OUTPUT_DIR / "02_llm"

######

INPUT_DIR_NAME = "input"
PROMPTS_DIR_NAME = "prompts"
OUTPUTS_DIR_NAME = "outputs"

######

###


DATA_CLEANING_OUTPUT_DIR = ARTIFACT_DIR / "04_data_cleaning"

CONSTRAINTS_OUTPUT_DIR = ARTIFACT_DIR / "05_constraints"

ETL_OUTPUT_DIR = ARTIFACT_DIR / "06_etl"

LOAD_DW_OUTPUT_DIR = ARTIFACT_DIR / "07_load_dw"

##############################################################
# ============================================================
# DATA QUALITY FILE NAMES 
# ============================================================
##############################################################

DQA_SCORECARD_FILE = "dq_scorecard_by_table.csv"

DQA_CHECK_RESULTS_FILE = "dq_check_results.csv"

DQA_ISSUES_FILE = "issues_all_tables.csv"

REFERENTIAL_INTEGRITY_ISSUES_FILE = "referential_integrity_issues.csv"


# ============================================================
# LLM INTERPRETATION FILE NAMES
# ============================================================

LLM_INPUT_JSON_FILE = "dqa_llm_input.json"
LLM_PROMPT_FILE = "dqa_interpretation_prompt.txt"
LLM_FULL_OUTPUT_FILE = "full_llm_output.md"


# ============================================================
# GENERAL DQA OUTPUT DIRECTORIES
# ============================================================

GENERAL_DQA_SCORECARDS_DIR = GENERAL_DQA_OUTPUT_DIR / SCORECARDS_DIR_NAME

GENERAL_DQA_ISSUES_DIR = GENERAL_DQA_OUTPUT_DIR / ISSUES_DIR_NAME

GENERAL_DQA_ISSUES_BY_TABLE_DIR = GENERAL_DQA_ISSUES_DIR / ISSUES_BY_TABLE_DIR_NAME

GENERAL_DQA_VISUALIZATIONS_DIR = GENERAL_DQA_OUTPUT_DIR / VISUALIZATIONS_DIR_NAME

GENERAL_DQA_VISUALIZATIONS_HTML_DIR = GENERAL_DQA_VISUALIZATIONS_DIR / HTML_DIR_NAME

GENERAL_DQA_VISUALIZATIONS_TABLES_DIR = GENERAL_DQA_VISUALIZATIONS_DIR / TABLES_DIR_NAME



# ============================================================
# LLM INTERPRETATION DIRECTORIES
# ============================================================

LLM_INPUT_DIR = LLM_OUTPUT_DIR / INPUT_DIR_NAME

LLM_PROMPTS_DIR = LLM_OUTPUT_DIR / PROMPTS_DIR_NAME

LLM_OUTPUTS_DIR = LLM_OUTPUT_DIR / OUTPUTS_DIR_NAME


# ============================================================
# LLM INTERPRETATION FILE PATHS
# ============================================================

LLM_INPUT_JSON_PATH = LLM_INPUT_DIR / LLM_INPUT_JSON_FILE

LLM_PROMPT_PATH = LLM_PROMPTS_DIR / LLM_PROMPT_FILE

LLM_FULL_OUTPUT_PATH = LLM_OUTPUTS_DIR / LLM_FULL_OUTPUT_FILE

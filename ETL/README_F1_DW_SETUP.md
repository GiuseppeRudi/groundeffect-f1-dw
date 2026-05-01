# F1 Data Warehouse Project - Environment Setup

This project uses Python scripts for two main phases:

1. **Data extraction from APIs** using FastF1 / Ergast

2. **Creation and loading of the reconciled PostgreSQL database** from CSV files

To keep the project reproducible, it is recommended to use a dedicated **Conda environment**.

---

## 1. Create and activate the Conda environment

```bash
conda create -n f1_dw python=3.11 -y
conda activate f1_dw
```

Then upgrade `pip` inside the environment:

```bash
python -m pip install --upgrade pip
```

---

## 2. Install required packages


```bash
pip install -r requirements.txt
```

## 3. Suggested workflow

### Step 1 - Extract data from FastF1 / Ergast

Run the extraction script that creates the reconciled CSV files.

Example:

```bash
python extract_fastf1_reconciled.py
```

This script typically produces CSV files such as:
- `season.csv`
- `event_weekend.csv`
- `session.csv`
- `session_result.csv`
- `lap_performance.csv`
- `session_weather.csv`
- `track_status.csv`
- `extraction_log.csv`
- `driver.csv`
- `team.csv`
- `season_driver.csv`
- `season_team.csv`

---

### Step 2 - Create and populate the reconciled PostgreSQL database

After the CSV files are generated, run the database loading script.

Example:

```bash
python load_reconciled_to_postgres.py
```

This script is expected to:
- read the CSV files
- create PostgreSQL tables
- load the data into the tables
- apply primary keys and foreign keys

---

## 5. PostgreSQL prerequisites

Before running the loading script, make sure that:

- The target database already exists, for example:

```sql
CREATE DATABASE f1_reconciled_db;
```

3. The connection string in the Python script is configured correctly, for example:

```python
DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/f1_reconciled_db"
```

Update username, password, host, port and database name according to your local setup.

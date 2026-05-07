"""
output_utils.py

Generic reusable output helpers for the pipeline.
"""

from __future__ import annotations

from pathlib import Path

import json
import pandas as pd


def ensure_dir(path: Path) -> Path:
    """
    Create a directory if it does not exist and return it.
    """

    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_dirs(paths: list[Path] | dict[str, Path]) -> list[Path] | dict[str, Path]:
    """
    Create multiple directories.

    It accepts either:
    - list[Path]
    - dict[str, Path]
    """

    if isinstance(paths, dict):
        for path in paths.values():
            ensure_dir(path)
        return paths

    for path in paths:
        ensure_dir(path)

    return paths


def write_csv(df: pd.DataFrame, path: Path, index: bool = False) -> Path:
    """
    Write a DataFrame to CSV after creating the parent directory.
    """

    ensure_dir(path.parent)
    df.to_csv(path, index=index)
    print(f"[OK] Saved CSV: {path}")
    return path


def write_empty_csv(columns: list[str], path: Path) -> Path:
    """
    Write an empty CSV with stable columns.
    """

    df = pd.DataFrame(columns=columns)
    return write_csv(df, path, index=False)


def write_partitioned_csv(
    df: pd.DataFrame,
    partition_column: str,
    output_dir: Path,
    filename_prefix: str,
) -> list[Path]:
    """
    Write one CSV file for each value of a partition column.

    Example:
        issues_lap.csv
        issues_result.csv
        issues_weather.csv
    """

    ensure_dir(output_dir)

    written_files: list[Path] = []

    if df.empty or partition_column not in df.columns:
        return written_files

    for value, group_df in df.groupby(partition_column):
        file_path = output_dir / f"{filename_prefix}_{value}.csv"
        write_csv(group_df, file_path, index=False)
        written_files.append(file_path)

    return written_files


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"[OK] Saved: {path}")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Saved: {path}")



from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PIPELINE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PIPELINE_ROOT.parent
CONFIG_PATH = PIPELINE_ROOT / "pipeline_steps.yaml"


@dataclass(frozen=True)
class PipelineStep:
    number: int
    name: str
    script_path: Path
    enabled: bool 


def load_yaml_config(config_path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is required to read pipeline_steps.yaml. "
            "Install the Conda environment with: conda env create -f environment.yml"
        ) from exc

    if not config_path.exists():
        raise FileNotFoundError(f"Pipeline config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not data:
        raise ValueError(f"Pipeline config file is empty: {config_path}")

    if "steps" not in data:
        raise ValueError("Invalid pipeline config: missing top-level 'steps' key.")

    return data


def load_steps(config_path: Path) -> list[PipelineStep]:
    config = load_yaml_config(config_path)
    raw_steps = config["steps"]

    if not isinstance(raw_steps, list):
        raise ValueError("Invalid pipeline config: 'steps' must be a list.")

    steps: list[PipelineStep] = []

    for raw_step in raw_steps:
        if raw_step is None:
            continue

        number = int(raw_step["number"])
        name = str(raw_step["name"])
        script = Path(str(raw_step["script"]))

        script_path = script if script.is_absolute() else PIPELINE_ROOT / script

        enabled = bool(raw_step.get("enabled", True))

        steps.append(
            PipelineStep(
                number=number,
                name=name,
                script_path=script_path,
                enabled=enabled,
            )
        )


    return sorted(steps, key=lambda step: step.number)



def parse_step_numbers(value: str | None) -> set[int]:
    if not value:
        return set()

    try:
        return {int(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Step numbers must be integers separated by commas, for example: 3,5,8"
        ) from exc


def print_pipeline_plan(steps: list[PipelineStep]) -> None:
    print("\nPIPELINE PLAN")
    print("-" * 80)

    for step in steps:
        relative_script = step.script_path.relative_to(PROJECT_ROOT)

        status = "ENABLED" if step.enabled else "DISABLED"

        print(f"{step.number:02d}. [{status}] {step.name}")
        print(f"    {relative_script}")

    print("-" * 80)


def build_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()

    pythonpath_parts = [
        str(PROJECT_ROOT),
        str(PIPELINE_ROOT),
    ]

    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)

    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

    return env


def run_step(step: PipelineStep) -> None:
    relative_script = step.script_path.relative_to(PROJECT_ROOT)

    print("\n" + "=" * 80)
    print(f"STEP {step.number}: {step.name}")
    print(f"SCRIPT: {relative_script}")
    print("=" * 80)

    if not step.script_path.exists():
        raise FileNotFoundError(f"Missing pipeline script: {relative_script}")



    result = subprocess.run(
        [sys.executable, str(step.script_path)],
        cwd=PROJECT_ROOT,
        env=build_subprocess_env(),
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Pipeline stopped at step {step.number}: {step.name}"
        )

    print(f"COMPLETED: STEP {step.number} - {step.name}")


def select_steps( steps: list[PipelineStep]) -> list[PipelineStep]:

    selected : list[PipelineStep] = []
    for step in steps:

        if step.enabled:
            selected.append(step)
            continue
    
    if not selected:
        raise ValueError("No pipeline steps selected.")

    return selected



def main() -> None:

    steps = load_steps(CONFIG_PATH)

    print("\nF1 DATA WAREHOUSE PIPELINE")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Pipeline root: {PIPELINE_ROOT}")

    print_pipeline_plan(steps)



    selected_steps = select_steps(steps=steps,)


    for step in selected_steps:
        run_step(step)

    print("\n" + "=" * 80)
    print("PIPELINE COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    main()

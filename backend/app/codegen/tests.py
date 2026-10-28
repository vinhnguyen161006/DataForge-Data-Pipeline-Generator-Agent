from typing import Any

import yaml

from app.agents.schemas import Constraint, DataDesign


def column_test(constraint: Constraint) -> Any:
    """Map a single-column constraint to a dbt data_test entry with optional arguments."""
    test_name: str = constraint.kind
    if test_name == "relationship":
        test_name = "relationships"

    if not constraint.params:
        return test_name

    return {test_name: constraint.params.copy()}


def model_test(constraint: Constraint) -> Any:
    """Map composite-unique or expression constraints to dataforge generic tests."""
    test_name = f"dataforge_{constraint.kind}"
    params = constraint.params.copy()

    if len(constraint.columns) > 1 and constraint.kind != "expression":
        params["columns"] = constraint.columns
    elif constraint.columns:
        params["column_name"] = constraint.columns[0]

    return {test_name: params}


def schema_yml(design: DataDesign) -> dict[str, str]:
    """Return schema configurations mapped by file path built ONLY from approved constraints."""
    layers_data: dict[str, dict[str, Any]] = {"silver": {"models": {}}, "mart": {"models": {}}}

    for constraint in design.constraints:
        layer = constraint.layer
        model_name = constraint.model

        if model_name not in layers_data[layer]["models"]:
            layers_data[layer]["models"][model_name] = {
                "name": model_name,
                "columns": {},
                "tests": [],
            }

        is_single = len(constraint.columns) == 1 and constraint.kind in [
            "not_null",
            "unique",
            "accepted_values",
            "relationship",
        ]

        test_entry = column_test(constraint) if is_single else model_test(constraint)

        if layer == "silver":
            if isinstance(test_entry, str):
                test_entry = {test_entry: {"config": {"severity": "warn"}}}
            else:
                key = next(iter(test_entry.keys()))
                if "config" not in test_entry[key]:
                    test_entry[key]["config"] = {}
                test_entry[key]["config"]["severity"] = "warn"

        if is_single:
            col_name = constraint.columns[0]
            if col_name not in layers_data[layer]["models"][model_name]["columns"]:
                layers_data[layer]["models"][model_name]["columns"][col_name] = {
                    "name": col_name,
                    "tests": [],
                }
            layers_data[layer]["models"][model_name]["columns"][col_name]["tests"].append(
                test_entry
            )
        else:
            layers_data[layer]["models"][model_name]["tests"].append(test_entry)

    result_files = {}
    for layer_name, data in layers_data.items():
        models_list = []
        for model_name, model_data in data["models"].items():
            final_model = {"name": model_name}
            cols_list = list(model_data["columns"].values())

            if cols_list:
                final_model["columns"] = cols_list
            if model_data["tests"]:
                final_model["tests"] = model_data["tests"]

            models_list.append(final_model)

        if models_list:
            output_data = {"version": 2, "models": models_list}
            result_files[f"models/{layer_name}/_schema.yml"] = yaml.dump(
                output_data, sort_keys=False, allow_unicode=True
            )

    return result_files

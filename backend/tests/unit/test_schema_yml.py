from app.agents.schemas import Constraint
from app.codegen.tests import schema_yml
from tests.designs import minimal_design


def test_schema_yml_covers_every_layer_with_approved_constraints() -> None:
    """Both silver and mart layers get a schema file when each has an approved constraint."""
    design = minimal_design().model_copy(
        update={
            "constraints": [
                Constraint(layer="silver", model="stg_orders", columns=["id"], kind="not_null"),
                Constraint(layer="mart", model="fct_orders", columns=["id"], kind="unique"),
            ]
        }
    )
    files = schema_yml(design)
    assert set(files) == {"models/silver/_schema.yml", "models/mart/_schema.yml"}
    assert "severity: warn" in files["models/silver/_schema.yml"]
    assert "severity" not in files["models/mart/_schema.yml"]

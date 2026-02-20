import json
from pathlib import Path
from typing import Any, Dict

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA_PATH = Path(__file__).parent / "schema.json"

class SchemaValidator:
    def __init__(self, schema_path: Path = SCHEMA_PATH):
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)
        
        # Check against draft 2020-12
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)

    def validate(self, instance: Any, def_name: str) -> None:
        """
        Validate an instance against a specific definition in the schema ($defs/def_name).
        Raises Exception if invalid.
        """
        # Create a tiny schema that exactly references the target definition
        target_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"#/$defs/{def_name}",
            "$defs": self.schema.get("$defs", {})
        }
        validator = Draft202012Validator(target_schema)
        
        errors = list(validator.iter_errors(instance))
        if errors:
            error_msgs = []
            for e in errors:
                path = " -> ".join(str(p) for p in e.absolute_path)
                error_msgs.append(f"Field '{path}': {e.message}")
            raise ValueError("Validation failed:\n" + "\n".join(error_msgs))

def parse_yaml_file(filepath: Path) -> Dict[str, Any]:
    """Parse YAML to JSON-compatible Python dict."""
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {filepath}: {e}")

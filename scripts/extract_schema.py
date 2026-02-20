import re
import json
from pathlib import Path

def extract_schema():
    spec_path = Path("docs/spec.md")
    schema_path = Path("src/nitbench/validation/schema.json")
    
    with open(spec_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    matches = re.findall(r"```json\n(.*?)\n```", content, re.DOTALL)
    for match in matches:
        try:
            data = json.loads(match)
            if "$id" in data and "nitbench:schema" in data["$id"]:
                with open(schema_path, "w", encoding="utf-8") as out:
                    json.dump(data, out, indent=2)
                print(f"Successfully extracted schema to {schema_path}")
                return
        except json.JSONDecodeError:
            continue
            
    print("Schema not found in spec.md")
    exit(1)

if __name__ == "__main__":
    extract_schema()

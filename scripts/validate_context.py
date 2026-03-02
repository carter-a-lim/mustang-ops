import json
import sys
from pathlib import Path

from jsonschema import validate

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.common import CONTEXT_PATH


def main() -> None:
    schema = json.loads(Path("schemas/mustang_context.schema.json").read_text())
    data = json.loads(CONTEXT_PATH.read_text())
    validate(instance=data, schema=schema)
    print("mustang_context.json is valid")


if __name__ == "__main__":
    main()

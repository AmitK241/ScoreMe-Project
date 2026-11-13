"""Intake validation. The schema comes from the workflow config, not from code."""

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def validate_input(schema, data):
    """Returns a list of human-readable errors. An empty list means the input is valid."""
    if not isinstance(data, dict):
        return ["request data must be a JSON object"]

    errors = []
    for name, spec in schema.items():
        if data.get(name) is None:
            if spec.get("required"):
                errors.append(f"'{name}' is required")
            continue
        value = data[name]
        if not _TYPE_CHECKS[spec["type"]](value):
            errors.append(f"'{name}' must be of type {spec['type']}")
            continue
        if "allowed" in spec and value not in spec["allowed"]:
            errors.append(f"'{name}' must be one of {spec['allowed']}")

    for name in data:
        if name not in schema:
            errors.append(f"unknown field '{name}'")
    return errors

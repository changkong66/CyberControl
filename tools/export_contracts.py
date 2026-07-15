from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from liyans_contracts.registry import CONTRACT_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "schemas"
TS_OUTPUT = ROOT / "packages" / "contracts-ts" / "src" / "generated"
GO_OUTPUT = ROOT / "packages" / "contracts-go" / "contracts"


def format_go_source(path: Path) -> None:
    """Apply the canonical Go formatter so generation is reproducible."""
    gofmt = shutil.which("gofmt")
    if gofmt is None:
        raise RuntimeError(
            "gofmt is required to export Go contracts; install the pinned Go toolchain first"
        )
    result = subprocess.run(  # noqa: S603
        [gofmt, "-w", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown gofmt failure"
        raise RuntimeError(f"gofmt failed for {path}: {detail}")


def ts_literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def ts_special_type(schema: dict[str, Any]) -> str | None:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return ts_literal(schema["const"])
    if "enum" in schema:
        return " | ".join(ts_literal(item) for item in schema["enum"])
    if "anyOf" in schema:
        return " | ".join(ts_type(item) for item in schema["anyOf"])
    return None


def ts_object_type(schema: dict[str, Any]) -> str:
    properties = schema.get("properties", {})
    if not properties and isinstance(schema.get("additionalProperties"), dict):
        return f"Record<string, {ts_type(schema['additionalProperties'])}>"
    required = set(schema.get("required", []))
    fields = [
        f"{json.dumps(name)}{'' if name in required else '?'}: {ts_type(field_schema)}"
        for name, field_schema in properties.items()
    ]
    return "{ " + "; ".join(fields) + " }"


def ts_type(schema: dict[str, Any]) -> str:
    special_type = ts_special_type(schema)
    if special_type is not None:
        return special_type

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return " | ".join(
            "null" if item == "null" else ts_type({**schema, "type": item}) for item in schema_type
        )
    if schema_type == "array":
        return f"Array<{ts_type(schema.get('items', {}))}>"
    if schema_type == "object" or "properties" in schema:
        return ts_object_type(schema)
    return {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
    }.get(schema_type, "unknown")


def render_interface(name: str, schema: dict[str, Any]) -> str:
    if schema.get("type") != "object" and "properties" not in schema:
        return f"export type {name} = {ts_type(schema)}\n"

    required = set(schema.get("required", []))
    lines = [f"export interface {name} {{"]
    for field_name, field_schema in schema.get("properties", {}).items():
        description = field_schema.get("description")
        if description:
            lines.append(f"  /** {description} */")
        optional = "" if field_name in required else "?"
        lines.append(f"  {json.dumps(field_name)}{optional}: {ts_type(field_schema)}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def go_name(name: str) -> str:
    parts = [part for part in re_split_identifier(name) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts)


def re_split_identifier(value: str) -> list[str]:
    normalized = ""
    for char in value:
        normalized += char if char.isalnum() else " "
    return normalized.split()


def go_literal_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int64"
    if isinstance(value, float):
        return "float64"
    return "string"


def go_union_type(options: list[dict[str, Any]]) -> str:
    non_null = [item for item in options if item.get("type") != "null"]
    nullable = len(non_null) != len(options)
    if len(non_null) != 1:
        return "any"
    item_type = go_type(non_null[0])
    if nullable and not item_type.startswith(("[]", "map[", "*")):
        return "*" + item_type
    return item_type


def go_special_type(schema: dict[str, Any]) -> str | None:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return go_literal_type(schema["const"])
    if "enum" in schema:
        values = schema["enum"]
        return go_literal_type(values[0]) if values else "string"
    if "anyOf" in schema:
        return go_union_type(schema["anyOf"])
    return None


def go_string_type(schema: dict[str, Any]) -> str:
    return {
        "uuid": "UUID",
        "date-time": "DateTime",
    }.get(schema.get("format"), "string")


def go_object_type(schema: dict[str, Any]) -> str:
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        return "map[string]" + go_type(additional)
    return "map[string]any"


def go_type(schema: dict[str, Any]) -> str:
    special_type = go_special_type(schema)
    if special_type is not None:
        return special_type

    schema_type = schema.get("type")
    if schema_type == "string":
        return go_string_type(schema)
    if schema_type == "array":
        return "[]" + go_type(schema.get("items", {}))
    if schema_type == "object" or "properties" in schema:
        return go_object_type(schema)
    return {
        "integer": "int64",
        "number": "float64",
        "boolean": "bool",
    }.get(schema_type, "any")


def render_go_definition(name: str, schema: dict[str, Any]) -> str:
    description = schema.get("description")
    lines: list[str] = []
    if description:
        lines.append(f"// {name} {description}")

    if "enum" in schema:
        lines.append(f"type {name} string")
        lines.append("")
        lines.append("const (")
        for value in schema["enum"]:
            constant_name = go_name(f"{name}_{value}")
            lines.append(f"\t{constant_name} {name} = {json.dumps(value)}")
        lines.append(")")
        return "\n".join(lines) + "\n"

    if schema.get("type") != "object" and "properties" not in schema:
        lines.append(f"type {name} {go_type(schema)}")
        return "\n".join(lines) + "\n"

    required = set(schema.get("required", []))
    lines.append(f"type {name} struct {{")
    for field_name, field_schema in schema.get("properties", {}).items():
        field_description = field_schema.get("description")
        if field_description:
            lines.append(f"\t// {field_description}")
        field_type = go_type(field_schema)
        optional = field_name not in required
        if optional and not field_type.startswith(("[]", "map[", "*")):
            field_type = "*" + field_type
        json_tag = field_name + (",omitempty" if optional else "")
        lines.append(f'\t{go_name(field_name)} {field_type} `json:"{json_tag}"`')
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    TS_OUTPUT.mkdir(parents=True, exist_ok=True)
    GO_OUTPUT.mkdir(parents=True, exist_ok=True)
    for generated_file in TS_OUTPUT.glob("*.ts"):
        generated_file.unlink()

    index: list[dict[str, str]] = []
    ts_definitions: dict[str, dict[str, Any]] = {}
    for registration in CONTRACT_REGISTRY:
        filename = f"{registration.schema_name}.schema.json"
        schema = registration.model.model_json_schema()
        (OUTPUT / filename).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        index.append(
            {
                "schema_name": registration.schema_name,
                "owner": registration.owner,
                "visibility": registration.visibility,
                "compatibility": registration.compatibility,
                "file": filename,
            }
        )

        for definition_name, definition in schema.get("$defs", {}).items():
            existing = ts_definitions.get(definition_name)
            if existing is not None and existing != definition:
                raise ValueError(f"conflicting TypeScript definition: {definition_name}")
            ts_definitions[definition_name] = definition
        root_name = schema.get("title", registration.model.__name__)
        root_schema = {key: value for key, value in schema.items() if key != "$defs"}
        existing_root = ts_definitions.get(root_name)
        if existing_root is not None and existing_root != root_schema:
            raise ValueError(f"conflicting TypeScript root definition: {root_name}")
        ts_definitions[root_name] = root_schema

    (OUTPUT / "registry.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    ts_sections = ["// Generated by tools/export_contracts.py. Do not edit.\n"]
    ts_sections.extend(
        render_interface(definition_name, ts_definitions[definition_name])
        for definition_name in sorted(ts_definitions)
    )
    (TS_OUTPUT / "contracts.ts").write_text(
        "\n".join(ts_sections),
        encoding="utf-8",
        newline="\n",
    )
    (TS_OUTPUT / "index.ts").write_text(
        '// Generated by tools/export_contracts.py. Do not edit.\nexport * from "./contracts"\n',
        encoding="utf-8",
        newline="\n",
    )

    go_sections = [
        "// Code generated by tools/export_contracts.py. DO NOT EDIT.\n",
        "package contracts\n",
        "type UUID string\n",
        "type DateTime string\n",
    ]
    go_sections.extend(
        render_go_definition(definition_name, ts_definitions[definition_name])
        for definition_name in sorted(ts_definitions)
    )
    go_contracts = GO_OUTPUT / "contracts.go"
    go_contracts.write_text(
        "\n".join(go_sections),
        encoding="utf-8",
        newline="\n",
    )
    format_go_source(go_contracts)


if __name__ == "__main__":
    main()

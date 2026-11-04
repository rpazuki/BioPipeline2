"""Extract supported Python class annotations inside a selected runtime generation."""

import json
import re
import shlex
from dataclasses import replace
from pathlib import Path

from app.domain.errors import ValidationFailed
from app.infrastructure.environments import CONTAINER_PATH, BuildFailed, GenerationBuilder

TYPE_INSPECTION = r"""
import dataclasses, datetime, enum, importlib, inspect, json, sys, types, typing

definitions, seen, notes = {}, {}, []

def field_spec(annotation):
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin in (typing.Annotated, typing.Required, typing.NotRequired):
        return field_spec(args[0])
    if origin in (typing.Union, types.UnionType):
        rest = [arg for arg in args if arg is not type(None)]
        if len(rest) == 1 and len(rest) != len(args):
            return dict(field_spec(rest[0]), nullable=True)
        raise ValueError("Only optional unions are supported; use a labelled choice instead.")
    if origin in (list, dict):
        if origin is dict and (len(args) != 2 or args[0] is not str):
            raise ValueError("Named maps need string keys and one annotated value type.")
        spec = field_spec(args[-1])
        if "container" in spec:
            raise ValueError("Nested collections need an intermediate named object type.")
        return dict(spec, container="list" if origin is list else "map")
    if origin is typing.Literal:
        return {"type":"enum", "options":[{"label":str(arg),"value":arg} for arg in args]}
    for python_type, name in ((str,"string"),(int,"integer"),(float,"number"),(bool,"boolean")):
        if annotation is python_type:
            return {"type":name}
    if annotation in (datetime.datetime, datetime.date):
        return {"type":"string", "format":"datetime"}
    if inspect.isclass(annotation) and issubclass(annotation, enum.Enum):
        return {"type":"enum", "options":[
            {"label":member.name,"value":member.value} for member in annotation]}
    supported_class = inspect.isclass(annotation) and (
        dataclasses.is_dataclass(annotation) or typing.is_typeddict(annotation)
        or hasattr(annotation,"model_fields"))
    if supported_class:
        return {"type":extract(annotation)}
    raise ValueError("Unsupported annotation: " + str(annotation))

def extract(cls):
    if not inspect.isclass(cls):
        raise ValueError("Select a dataclass, TypedDict, or Pydantic model class.")
    if cls in seen:
        return seen[cls]
    name = cls.__name__
    while name in definitions:
        name += "_"
    seen[cls] = name
    definitions[name] = {"fields":{}}
    hints = typing.get_type_hints(cls, include_extras=True)
    dc_fields = {f.name:f for f in dataclasses.fields(cls)} if dataclasses.is_dataclass(cls) else {}
    model_fields = getattr(cls,"model_fields",{})
    for key, annotation in hints.items():
        if typing.get_origin(annotation) is typing.ClassVar:
            continue
        spec = dict(field_spec(annotation))
        spec.setdefault("nullable",False)
        required = key in getattr(cls,"__required_keys__",hints)
        if typing.get_origin(annotation) is typing.NotRequired:
            required = False
        elif typing.get_origin(annotation) is typing.Required:
            required = True
        if key in dc_fields:
            field = dc_fields[key]
            required = (field.default is dataclasses.MISSING
                        and field.default_factory is dataclasses.MISSING)
            if field.default is not dataclasses.MISSING:
                spec["default"] = field.default
            if field.default_factory is not dataclasses.MISSING:
                notes.append(name + "." + key + ": default factory was not executed.")
            if isinstance(field.metadata.get("help"),str):
                spec["help"] = field.metadata["help"]
        elif key in model_fields:
            field = model_fields[key]
            required = field.is_required()
            if not required and field.default_factory is None:
                spec["default"] = field.default
            if field.description:
                spec["help"] = field.description
            notes.append(name + "." + key + ": review any custom model validators separately.")
        spec["required"] = required
        try:
            json.dumps(spec,allow_nan=False)
        except (TypeError,ValueError):
            spec.pop("default",None)
            notes.append(name + "." + key + ": non-JSON default was not imported.")
        definitions[name]["fields"][key] = spec
    return name

module, name = sys.argv[1].rsplit(".",1)
cls = getattr(importlib.import_module(module),name)
root = extract(cls)
print(json.dumps({"root":root,"definitions":definitions,"notes":notes},allow_nan=False))
"""


def extract_types(builder: GenerationBuilder, path: Path, class_path: str) -> dict:
    """Inspect one qualified class without importing its module into the API process.

    Returns extracted definitions and review notes. Unsupported annotations,
    recursive definitions, and unavailable classes are reported as errors.
    """
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", class_path, flags=re.ASCII):
        raise ValidationFailed(
            "Enter a fully qualified class name, such as package.module.Options."
        )
    result = replace(builder, timeout_seconds=min(builder.timeout_seconds, 60))._run(
        path,
        f"{CONTAINER_PATH}/bin/python -c {shlex.quote(TYPE_INSPECTION)} {shlex.quote(class_path)}",
        writable=False,
    )
    if result.returncode:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise BuildFailed(
            f"The class could not be inspected. {lines[-1] if lines else ''}",
            log=result.stdout + result.stderr,
        )
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as error:
        raise BuildFailed("The class inspection returned unreadable output.") from error

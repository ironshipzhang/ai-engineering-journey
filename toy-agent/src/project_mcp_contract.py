"""F's shared wire contract; project lookup remains in deepseek_summary."""
from copy import deepcopy

import deepseek_summary as business

DESCRIPTION = "只读查询虚构项目的 ID、名称与概况，不含问题列表。"
INPUT_SCHEMA = {"type": "object", "properties": {"project_id": {"type": "string", "minLength": 1}},
                "required": ["project_id"], "additionalProperties": False}
OUTPUT_SCHEMA = {"type": "object", "properties": {
    key: {"type": "string", "minLength": 1} for key in ("project_id", "name", "status")},
    "required": ["project_id", "name", "status"], "additionalProperties": False}
MODEL_TOOL = {"type": "function", "function": {"name": "get_project", "description": DESCRIPTION,
                                               "parameters": deepcopy(INPUT_SCHEMA)}}


class ContractError(Exception):
    """Local fixed diagnostic only, never a remote exception's text."""


def require(condition):
    if not condition:
        raise ContractError("项目工具契约不符合要求")


def parameters(params, target=None):
    require(isinstance(params, dict) and set(params) == {"project_id"})
    value = params["project_id"]
    require(isinstance(value, str) and bool(value.strip()))
    if target is not None:
        business.validate_project_parameters(params, target)
    return value


def project(value, target=None):
    require(isinstance(value, dict) and set(value) == {"project_id", "name", "status"})
    require(all(isinstance(v, str) and bool(v.strip()) for v in value.values()))
    require(target is None or value["project_id"] == target)
    return value


def query(params, snapshot):
    return project(business.get_project(parameters(params), snapshot))

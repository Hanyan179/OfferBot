#!/usr/bin/env python3
"""
Doc Generator — 从 ToolRegistry 自动内省所有已注册 Tool，生成 Markdown 文档

流程: create_tool_registry → introspect → format → write
每步均为纯函数，可独立测试。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 确保 boss-agent 根目录在 sys.path 中
_BOSS_AGENT_ROOT = Path(__file__).resolve().parent.parent
if str(_BOSS_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOSS_AGENT_ROOT))

from agent.tool_registry import Tool, ToolRegistry


# ---------------------------------------------------------------------------
# 2.1  introspect_tool
# ---------------------------------------------------------------------------


def introspect_tool(tool: Tool) -> dict:
    """从 Tool 实例提取结构化信息。

    Returns:
        ToolInfo dict: {name, display_name, description, category, toolset,
                        concurrency_safe, parameters: [ParameterInfo...]}
    """
    schema = tool.parameters_schema or {}
    properties: dict[str, Any] = schema.get("properties", {})
    required_list: list[str] = schema.get("required", [])

    parameters: list[dict] = []
    for param_name, prop in properties.items():
        param_info: dict[str, Any] = {
            "name": param_name,
            "type": prop.get("type", "string"),
            "required": param_name in required_list,
            "description": prop.get("description", ""),
        }
        if "enum" in prop:
            param_info["enum"] = prop["enum"]
        if "default" in prop:
            param_info["default"] = prop["default"]
        parameters.append(param_info)

    return {
        "name": tool.name,
        "display_name": tool.display_name,
        "description": tool.description or "(无描述)",
        "category": tool.category,
        "toolset": tool.toolset,
        "concurrency_safe": tool.is_concurrency_safe,
        "parameters": parameters,
    }


# ---------------------------------------------------------------------------
# 2.2  format_parameter_table
# ---------------------------------------------------------------------------


def format_parameter_table(properties: dict, required: list[str]) -> str:
    """将 JSON Schema properties 格式化为 Markdown 参数表格。

    Args:
        properties: JSON Schema 的 properties 字典
        required: 必填参数名列表

    Returns:
        Markdown 表格字符串；properties 为空时返回空字符串。
    """
    if not properties:
        return ""

    lines = [
        "| 参数 | 类型 | 必填 | 描述 |",
        "|------|------|------|------|",
    ]
    for param_name, prop in properties.items():
        p_type = prop.get("type", "string")
        is_req = "✅" if param_name in required else ""
        desc = prop.get("description", "")
        # 附加 enum 信息
        if "enum" in prop:
            enum_str = ", ".join(f"`{v}`" for v in prop["enum"])
            desc = f"{desc} (可选值: {enum_str})" if desc else f"可选值: {enum_str}"
        # 附加 default 信息
        if "default" in prop:
            desc = f"{desc} (默认: `{prop['default']}`)" if desc else f"默认: `{prop['default']}`"
        lines.append(f"| `{param_name}` | `{p_type}` | {is_req} | {desc} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2.3  format_tool_section
# ---------------------------------------------------------------------------


def format_tool_section(tool_info: dict) -> str:
    """将结构化 ToolInfo 格式化为完整的 Markdown 段落。

    Args:
        tool_info: introspect_tool 返回的字典

    Returns:
        单个 Tool 的 Markdown 文档段落。
    """
    name = tool_info["name"]
    display_name = tool_info["display_name"]
    description = tool_info["description"] or "(无描述)"
    category = tool_info["category"]
    toolset = tool_info["toolset"]
    concurrency = "✅ 是" if tool_info["concurrency_safe"] else "❌ 否"

    lines = [
        f"### `{name}` — {display_name}",
        "",
        f"> {description}",
        "",
        f"- **分类**: {category}",
        f"- **工具集**: {toolset}",
        f"- **并发安全**: {concurrency}",
        "",
    ]

    # 参数表格
    params = tool_info.get("parameters", [])
    if params:
        # 从 parameters 列表重建 properties/required 以复用 format_parameter_table
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in params:
            prop: dict[str, Any] = {
                "type": p.get("type", "string"),
                "description": p.get("description", ""),
            }
            if "enum" in p:
                prop["enum"] = p["enum"]
            if "default" in p:
                prop["default"] = p["default"]
            properties[p["name"]] = prop
            if p.get("required"):
                required.append(p["name"])

        table = format_parameter_table(properties, required)
        if table:
            lines.append("**参数:**")
            lines.append("")
            lines.append(table)
            lines.append("")
    else:
        lines.append("**参数:** 无")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2.4  generate_catalog
# ---------------------------------------------------------------------------

# 分类显示顺序和中文名
_CATEGORY_ORDER = ["data", "memory", "getjob", "browser", "ai"]
_CATEGORY_NAMES = {
    "data": "数据工具 (data)",
    "memory": "记忆工具 (memory)",
    "getjob": "求职平台工具 (getjob)",
    "browser": "浏览器工具 (browser)",
    "ai": "AI 工具 (ai)",
}


def generate_catalog(registry: ToolRegistry) -> str:
    """按 category 分组生成完整的 Tool Catalog Markdown 文档。

    Args:
        registry: 已注册所有 Tool 的 ToolRegistry 实例

    Returns:
        完整的 Markdown 文档字符串。
    """
    # 内省所有 Tool
    all_tools: list[dict] = []
    for name in registry.list_tool_names():
        tool = registry.get_tool(name)
        if tool is not None:
            all_tools.append(introspect_tool(tool))

    # 按 category 分组
    grouped: dict[str, list[dict]] = {}
    for info in all_tools:
        cat = info["category"]
        grouped.setdefault(cat, []).append(info)

    # 生成文档
    lines = [
        "# Tools API Reference",
        "",
        f"> 自动生成，共 {len(all_tools)} 个工具",
        "",
    ]

    # 目录
    lines.append("## 目录")
    lines.append("")
    for cat in _CATEGORY_ORDER:
        if cat in grouped:
            cat_name = _CATEGORY_NAMES.get(cat, cat)
            lines.append(f"- [{cat_name}](#{cat})")
    # 处理未在预定义顺序中的分类
    for cat in sorted(grouped.keys()):
        if cat not in _CATEGORY_ORDER:
            cat_name = _CATEGORY_NAMES.get(cat, cat)
            lines.append(f"- [{cat_name}](#{cat})")
    lines.append("")

    # 各分类段落
    for cat in _CATEGORY_ORDER:
        if cat not in grouped:
            continue
        cat_name = _CATEGORY_NAMES.get(cat, cat)
        lines.append(f"## {cat_name}")
        lines.append("")
        for info in sorted(grouped[cat], key=lambda x: x["name"]):
            lines.append(format_tool_section(info))
        lines.append("---")
        lines.append("")

    # 处理未在预定义顺序中的分类
    for cat in sorted(grouped.keys()):
        if cat in _CATEGORY_ORDER:
            continue
        cat_name = _CATEGORY_NAMES.get(cat, cat)
        lines.append(f"## {cat_name}")
        lines.append("")
        for info in sorted(grouped[cat], key=lambda x: x["name"]):
            lines.append(format_tool_section(info))
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2.5  main
# ---------------------------------------------------------------------------


def main() -> None:
    """入口：create_tool_registry → generate_catalog → 写入文件。"""
    from agent.bootstrap import create_tool_registry

    print("正在创建 ToolRegistry ...")
    registry, _skill_loader = create_tool_registry()
    print(f"已注册 {registry.tool_count} 个工具")

    print("正在生成文档 ...")
    markdown = generate_catalog(registry)

    output_path = _BOSS_AGENT_ROOT / "docs" / "tools-api-reference.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"文档已写入: {output_path}")


if __name__ == "__main__":
    main()

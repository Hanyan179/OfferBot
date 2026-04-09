#!/usr/bin/env python3
"""
Tool 关系图谱自动生成器

从代码中自动提取：
1. 所有注册的 Tool 的 name / category / toolset / context_deps / response_schema
2. 所有 Skill 文件的 allowed-tools 引用
3. Tool → Skill 的反向引用关系
4. 一致性检查（Skill 引用了未注册的 Tool？Tool 没被任何 Skill 引用？）

用法：
    python3 scripts/tool_graph.py              # 输出到 stdout
    python3 scripts/tool_graph.py --json       # JSON 格式输出
    python3 scripts/tool_graph.py --check      # 只做一致性检查
    python3 scripts/tool_graph.py --markdown   # 生成 Markdown 报告
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 让 import 能找到 boss-agent 下的模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_registry():
    """加载 ToolRegistry，获取所有注册的 Tool。"""
    from agent.bootstrap import create_tool_registry
    registry, skill_loader = create_tool_registry()
    return registry, skill_loader


def _extract_tool_info(registry) -> list[dict]:
    """从 registry 中提取每个 Tool 的元信息。"""
    tools = []
    for name in registry.list_tool_names():
        tool = registry.get_tool(name)
        if tool is None:
            continue
        info = {
            "name": tool.name,
            "display_name": tool.display_name,
            "description": tool.description,
            "category": tool.category,
            "toolset": tool.toolset,
            "concurrency_safe": tool.is_concurrency_safe,
            "context_deps": tool.context_deps,
            "parameters_schema": tool.parameters_schema,
            "response_schema": tool.response_schema,
        }
        tools.append(info)
    return tools


def _extract_skill_refs(skill_loader) -> list[dict]:
    """从 SkillLoader 中提取所有 Skill 的 allowed-tools 引用。"""
    skills = []
    for name in skill_loader.get_all_skill_names():
        content = skill_loader.get_skill_content(name)
        if content is None:
            continue
        skills.append({
            "name": name,
            "description": content.get("description", ""),
            "allowed_tools": content.get("allowed_tools", []),
        })
    return skills


def _build_reverse_map(tools: list[dict], skills: list[dict]) -> dict:
    """构建 Tool → 被哪些 Skill 引用 的反向映射。"""
    reverse: dict[str, list[str]] = {t["name"]: [] for t in tools}
    for skill in skills:
        for tool_name in skill["allowed_tools"]:
            if tool_name in reverse:
                reverse[tool_name].append(skill["name"])
            # 未注册的 tool 不加入 reverse（会在 check 中报告）
    return reverse


def _check_consistency(tools: list[dict], skills: list[dict]) -> list[str]:
    """一致性检查，返回问题列表。"""
    issues = []
    registered = {t["name"] for t in tools}

    # 1. Skill 引用了未注册的 Tool
    for skill in skills:
        for tool_name in skill["allowed_tools"]:
            if tool_name not in registered:
                issues.append(
                    f"⚠️  Skill '{skill['name']}' 引用了未注册的 Tool: '{tool_name}'"
                )

    # 2. Tool 没被任何 Skill 引用（孤立 Tool）
    referenced = set()
    for skill in skills:
        referenced.update(skill["allowed_tools"])
    for t in tools:
        if t["name"] not in referenced:
            issues.append(f"ℹ️  Tool '{t['name']}' 未被任何 Skill 引用")

    # 3. Tool 没有声明 response_schema
    for t in tools:
        if not t["response_schema"]:
            issues.append(f"📝 Tool '{t['name']}' 未声明 response_schema")

    # 4. Tool 没有声明 context_deps
    for t in tools:
        if not t["context_deps"]:
            issues.append(f"📝 Tool '{t['name']}' 未声明 context_deps")

    return issues


def _format_text(tools, skills, reverse_map, issues) -> str:
    """纯文本格式输出。"""
    lines = []
    lines.append("=" * 60)
    lines.append("Tool 关系图谱")
    lines.append("=" * 60)

    # 按 category 分组
    by_cat: dict[str, list[dict]] = {}
    for t in tools:
        by_cat.setdefault(t["category"], []).append(t)

    for cat, cat_tools in sorted(by_cat.items()):
        lines.append(f"\n## {cat} ({len(cat_tools)} tools)")
        lines.append("-" * 40)
        for t in cat_tools:
            refs = reverse_map.get(t["name"], [])
            ref_str = ", ".join(refs) if refs else "(无引用)"
            deps_str = ", ".join(t["context_deps"]) if t["context_deps"] else "(未声明)"
            lines.append(f"  {t['name']}")
            lines.append(f"    显示名: {t['display_name']}")
            lines.append(f"    toolset: {t['toolset']}")
            lines.append(f"    context: {deps_str}")
            lines.append(f"    被引用: {ref_str}")
            has_resp = "✅" if t["response_schema"] else "❌"
            lines.append(f"    response_schema: {has_resp}")

    lines.append(f"\n{'=' * 60}")
    lines.append(f"Skill 引用关系 ({len(skills)} skills)")
    lines.append("=" * 60)
    for skill in skills:
        lines.append(f"\n  {skill['name']}")
        lines.append(f"    tools: {', '.join(skill['allowed_tools'])}")

    if issues:
        lines.append(f"\n{'=' * 60}")
        lines.append(f"一致性检查 ({len(issues)} 项)")
        lines.append("=" * 60)
        for issue in issues:
            lines.append(f"  {issue}")

    lines.append(f"\n总计: {len(tools)} Tools, {len(skills)} Skills")
    return "\n".join(lines)


def _format_markdown(tools, skills, reverse_map, issues) -> str:
    """Markdown 格式输出。"""
    lines = []
    lines.append("# Tool 关系图谱\n")
    lines.append(f"> 自动生成，共 {len(tools)} Tools, {len(skills)} Skills\n")

    # 总览表
    lines.append("## 总览\n")
    lines.append("| Tool | 显示名 | 分类 | Toolset | Context | 被引用 | Response Schema |")
    lines.append("|------|--------|------|---------|---------|--------|-----------------|")
    for t in tools:
        refs = reverse_map.get(t["name"], [])
        ref_str = ", ".join(refs) if refs else "-"
        deps_str = ", ".join(t["context_deps"]) if t["context_deps"] else "-"
        has_resp = "✅" if t["response_schema"] else "❌"
        lines.append(f"| `{t['name']}` | {t['display_name']} | {t['category']} | {t['toolset']} | {deps_str} | {ref_str} | {has_resp} |")

    # Skill 引用
    lines.append("\n## Skill → Tool 引用\n")
    for skill in skills:
        lines.append(f"### {skill['name']}\n")
        lines.append(f"- 描述: {skill['description']}")
        lines.append(f"- Tools: `{'`, `'.join(skill['allowed_tools'])}`\n")

    # 一致性检查
    if issues:
        lines.append("\n## 一致性检查\n")
        for issue in issues:
            lines.append(f"- {issue}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Tool 关系图谱自动生成器")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--markdown", action="store_true", help="Markdown 格式输出")
    parser.add_argument("--check", action="store_true", help="只做一致性检查")
    parser.add_argument("--output", "-o", type=str, help="输出到文件")
    args = parser.parse_args()

    registry, skill_loader = _load_registry()
    tools = _extract_tool_info(registry)
    skills = _extract_skill_refs(skill_loader)
    reverse_map = _build_reverse_map(tools, skills)
    issues = _check_consistency(tools, skills)

    if args.check:
        if not issues:
            print("✅ 一致性检查通过，无问题。")
            sys.exit(0)
        print(f"发现 {len(issues)} 个问题：\n")
        for issue in issues:
            print(f"  {issue}")
        # 只有 ⚠️ 级别的问题才返回非零退出码
        has_warnings = any("⚠️" in i for i in issues)
        sys.exit(1 if has_warnings else 0)

    if args.json:
        data = {
            "tools": tools,
            "skills": skills,
            "reverse_map": reverse_map,
            "issues": issues,
            "summary": {
                "total_tools": len(tools),
                "total_skills": len(skills),
                "total_issues": len(issues),
            },
        }
        output = json.dumps(data, ensure_ascii=False, indent=2)
    elif args.markdown:
        output = _format_markdown(tools, skills, reverse_map, issues)
    else:
        output = _format_text(tools, skills, reverse_map, issues)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"已输出到 {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()

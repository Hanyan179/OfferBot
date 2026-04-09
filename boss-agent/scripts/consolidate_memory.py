"""
记忆画像聚合清理 — LLM 两步法：判断 + 合并。

步骤：
  1. 逐文件处理，每个文件先备份
  2. LLM 第一步：看所有条目标题+摘要，输出哪些组需要合并（JSON）
  3. LLM 第二步：每组只传那几条的完整内容，LLM 合并为一条
  4. 程序把合并结果替换回文件，未涉及的条目原样保留

用法: python3 scripts/consolidate_memory.py &
结果: scripts/output/consolidate_report.md
备份: data/记忆画像/*.md.bak
"""

import asyncio
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm_client import LLMClient
from config import load_config
from db.database import Database
from tools.data.memory_tools import CATEGORY_FILE_MAP, _get_display_name, _parse_sections

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
REPORT_FILE = OUTPUT_DIR / "consolidate_report.md"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("consolidate")

_FILE_TO_CATEGORY = {v: k for k, v in CATEGORY_FILE_MAP.items()}

# ── 第一步 Prompt：判断哪些条目需要合并 ──

JUDGE_PROMPT = """\
你是记忆画像整理助手。下面是「{category_name}」分类中所有条目的标题和内容摘要。

{entries_summary}

请判断哪些条目在说同一件事（内容重复或高度重叠），需要合并。

规则：
- 只看内容语义，不只看标题
- 不重复的条目不要动
- 输出需要合并的分组，每组包含条目编号（从0开始）

严格输出 JSON，不要输出其他内容：
```json
{{"merge_groups": [[0, 3], [1, 5, 7]], "reason": "简要说明每组为什么合并"}}
```

如果没有需要合并的，输出：
```json
{{"merge_groups": [], "reason": "无重复"}}
```
"""

# ── 第二步 Prompt：合并特定条目 ──

MERGE_PROMPT = """\
下面是用户记忆画像中「{category_name}」分类下的 {count} 个条目，它们内容重叠需要合并为一个。

{entries_full}

请合并为一个条目，要求：
1. 保留所有有价值的信息和细节，不丢失任何内容
2. 去除重复表述
3. 给出清晰具体的标题

严格输出 JSON：
```json
{{"title": "合并后标题", "content": "合并后完整内容"}}
```
"""


async def load_llm_config(db: Database) -> dict | None:
    result = {}
    for key in ("llm_api_key", "llm_base_url", "llm_model"):
        rows = await db.execute("SELECT value FROM user_preferences WHERE key = ?", (key,))
        result[key] = rows[0]["value"] if rows else ""
    if not result.get("llm_api_key"):
        return None
    return {"api_key": result["llm_api_key"], "base_url": result["llm_base_url"], "model": result["llm_model"]}


def parse_json_response(raw: str) -> dict | list | None:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def process_file(llm: LLMClient, md_file: Path, category: str, report: list[str]) -> None:
    content = md_file.read_text(encoding="utf-8")
    sections = _parse_sections(content)
    category_name = _get_display_name(category)

    if len(sections) <= 1:
        report.append(f"### {md_file.name}\n\n跳过（{len(sections)} 条）\n")
        return

    # ── 第一步：LLM 判断哪些需要合并 ──

    entries_summary = "\n".join(
        f"[{i}] 标题: {s['title']}\n    摘要: {s['body'][:100]}..."
        if len(s['body']) > 100 else
        f"[{i}] 标题: {s['title']}\n    内容: {s['body']}"
        for i, s in enumerate(sections)
    )

    judge_prompt = JUDGE_PROMPT.format(
        category_name=category_name,
        entries_summary=entries_summary,
    )

    try:
        raw = await llm.chat([{"role": "system", "content": judge_prompt}])
    except Exception as e:
        report.append(f"### {md_file.name}\n\n❌ 判断阶段 LLM 失败: {e}\n")
        return

    result = parse_json_response(raw)
    if not isinstance(result, dict) or "merge_groups" not in result:
        report.append(f"### {md_file.name}\n\n❌ 判断阶段返回格式错误\n\n```\n{raw[:300]}\n```\n")
        return

    merge_groups = result["merge_groups"]
    reason = result.get("reason", "")

    if not merge_groups:
        report.append(f"### {md_file.name}\n\n跳过（{len(sections)} 条，LLM 判断无重复）\n")
        return

    # 备份
    bak_path = md_file.with_suffix(".md.bak")
    shutil.copy2(md_file, bak_path)
    logger.info("备份 %s → %s", md_file.name, bak_path.name)

    report.append(f"### {md_file.name}\n\n原始 {len(sections)} 条，LLM 判断理由: {reason}\n")

    # ── 第二步：逐组合并 ──

    merged_indices: set[int] = set()
    new_entries: list[dict] = []

    for group in merge_groups:
        # 校验索引
        valid = [i for i in group if 0 <= i < len(sections)]
        if len(valid) < 2:
            continue

        entries_full = "\n\n".join(
            f"### 条目 [{i}]: {sections[i]['title']}\n{sections[i]['body']}"
            for i in valid
        )

        merge_prompt = MERGE_PROMPT.format(
            category_name=category_name,
            count=len(valid),
            entries_full=entries_full,
        )

        try:
            raw2 = await llm.chat([{"role": "system", "content": merge_prompt}])
        except Exception as e:
            report.append(f"  ⚠️ 合并组 {valid} 失败: {e}\n")
            continue

        merged = parse_json_response(raw2)
        if not isinstance(merged, dict) or "title" not in merged or "content" not in merged:
            report.append(f"  ⚠️ 合并组 {valid} 返回格式错误，保留原条目\n")
            continue

        old_titles = [sections[i]["title"] for i in valid]
        merged_indices.update(valid)
        new_entries.append(merged)
        report.append(f"  ✅ {old_titles} → \"{merged['title']}\"\n")
        logger.info("合并 %s: %s → %s", md_file.name, old_titles, merged["title"])

    # ── 重建文件：未合并的原样保留 + 合并后的新条目 ──

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [f"# {category_name}\n"]

    for i, s in enumerate(sections):
        if i not in merged_indices:
            # 原样保留（用原始 raw 文本）
            parts.append(s["raw"])

    for e in new_entries:
        parts.append(f"## {e['title']}\n{e['content']}\n\n> 聚合整理于: {now}")

    new_content = "\n\n".join(parts) + "\n"
    md_file.write_text(new_content, encoding="utf-8")

    new_sections = _parse_sections(new_content)
    report.append(f"\n  结果: {len(sections)} → {len(new_sections)} 条\n")


async def main():
    report: list[str] = [
        f"# 记忆画像聚合清理报告\n\n> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    ]

    config = load_config()
    db = Database(config.db_path)
    await db.connect()
    await db.init_schema()

    llm_config = await load_llm_config(db)
    if not llm_config:
        report.append("❌ 无 LLM 配置")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text("\n".join(report), encoding="utf-8")
        return

    llm = LLMClient(**llm_config)
    memory_dir = Path(config.memory_dir)

    # 支持命令行指定文件名，不指定则全量
    target_files = set(sys.argv[1:]) if len(sys.argv) > 1 else None

    for md_file in sorted(memory_dir.glob("*.md")):
        if target_files and md_file.name not in target_files:
            continue
        category = _FILE_TO_CATEGORY.get(md_file.name, md_file.stem)
        await process_file(llm, md_file, category, report)

    await db.close()

    report.append("---\n✅ 清理完成")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(report), encoding="utf-8")
    print(f"✅ 报告已写入 {REPORT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())

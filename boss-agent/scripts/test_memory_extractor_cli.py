"""
CLI 测试 MemoryExtractor — 后台独立进程运行，结果写入文件。

用法: python3 scripts/test_memory_extractor_cli.py &
结果: scripts/output/memory_test_result.md
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm_client import LLMClient
from agent.memory_extractor import MemoryExtractor
from config import load_config
from db.database import Database
from tools.data.memory_tools import _parse_sections

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "memory_test_result.md"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def snapshot(memory_dir: Path) -> str:
    """返回当前记忆状态的文本快照。"""
    if not memory_dir.exists():
        return "（空）\n"
    lines = []
    total = 0
    for md_file in sorted(memory_dir.glob("*.md")):
        sections = _parse_sections(md_file.read_text(encoding="utf-8"))
        total += len(sections)
        if sections:
            lines.append(f"  📁 {md_file.name} ({len(sections)} 条)")
            for s in sections:
                lines.append(f"     • {s['title']}")
    lines.append(f"\n  总计: {total} 条")
    return "\n".join(lines)


async def load_llm_config(db: Database) -> dict | None:
    result = {}
    for key in ("llm_api_key", "llm_base_url", "llm_model"):
        rows = await db.execute("SELECT value FROM user_preferences WHERE key = ?", (key,))
        result[key] = rows[0]["value"] if rows else ""
    if not result.get("llm_api_key"):
        return None
    return {"api_key": result["llm_api_key"], "base_url": result["llm_base_url"], "model": result["llm_model"]}


async def main():
    out = []
    out.append(f"# MemoryExtractor 测试报告\n\n> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    config = load_config()
    db = Database(config.db_path)
    await db.connect()
    await db.init_schema()

    llm_config = await load_llm_config(db)
    if not llm_config:
        out.append("❌ 数据库中没有 LLM 配置")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text("\n".join(out), encoding="utf-8")
        return

    llm_client = LLMClient(**llm_config)
    extractor = MemoryExtractor(llm_client=llm_client)
    memory_dir = Path(config.memory_dir)

    # --- 提取前 ---
    out.append(f"## 提取前\n\n```\n{snapshot(memory_dir)}\n```\n")

    # --- 第一次提取 ---
    msgs1 = [
        {"role": "user", "content": "我是一个全栈工程师，主要做 Python 和 React，在上海工作3年了。最近在看 AI 方向的机会，希望薪资 30-50K。"},
        {"role": "assistant", "content": "了解！你有 Python + React 的全栈背景，3年经验，在上海，想转 AI 方向，期望 30-50K。"},
        {"role": "user", "content": "对，我最近在学 LangChain 和 RAG，做了一个知识库问答的项目。我比较看重技术氛围，不想去太卷的公司。"},
        {"role": "assistant", "content": "不错，LangChain + RAG 是现在 AI 应用开发的核心技能。你有实际项目经验这点很加分。"},
    ]
    out.append("## 第一次提取\n\n对话：全栈工程师、Python/React、上海、AI方向、30-50K、LangChain/RAG\n")
    await extractor.extract(msgs1, {"conversation_id": "test-001"})
    out.append(f"```\n{snapshot(memory_dir)}\n```\n")

    # --- 第二次提取（相同内容，验证去重） ---
    out.append("## 第二次提取（相同对话，验证去重）\n")
    await extractor.extract(msgs1, {"conversation_id": "test-002"})
    out.append(f"```\n{snapshot(memory_dir)}\n```\n")

    # --- 第三次提取（更新信息） ---
    msgs2 = [
        {"role": "user", "content": "我改主意了，薪资期望提高到 40-60K，而且我现在更想去杭州发展。"},
        {"role": "assistant", "content": "好的，更新你的求职目标：杭州，40-60K。"},
    ]
    out.append("## 第三次提取（更新：杭州、40-60K）\n")
    await extractor.extract(msgs2, {"conversation_id": "test-003"})
    out.append(f"```\n{snapshot(memory_dir)}\n```\n")

    await db.close()
    out.append("---\n✅ 测试完成")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text("\n".join(out), encoding="utf-8")
    print(f"✅ 结果已写入 {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())

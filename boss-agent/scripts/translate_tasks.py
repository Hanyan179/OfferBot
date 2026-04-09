"""批量翻译 O*NET 任务描述为中文。

生成 data/economic_index/task_translations.json（英文 → 中文映射）。
分批调 LLM，每批 50 条，断点续翻。

用法：
  cd boss-agent
  python scripts/translate_tasks.py
"""

import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_DIR = Path(__file__).parent.parent / "data" / "economic_index"
OUTPUT = DATA_DIR / "task_translations.json"
BATCH_SIZE = 50


def _parse_args():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--provider", choices=["gemini", "db"], default="db",
                   help="LLM provider: gemini (直接用 google-genai) 或 db (从数据库读配置)")
    p.add_argument("--model", default="gemini-2.0-flash", help="Gemini model name")
    return p.parse_args()


async def main():
    args = _parse_args()

    if args.provider == "gemini":
        from google import genai
        client_genai = genai.Client(http_options={"api_version": "v1beta"})
        api_key = base_url = model = None  # not used
    else:
        from config import load_config
        from db.database import Database
        client_genai = None
        config = load_config()
        db = Database(config.db_path)
        await db.connect()
        settings = {}
        for key in ("llm_api_key", "llm_base_url", "llm_model"):
            rows = await db.execute("SELECT value FROM user_preferences WHERE key = ?", (key,))
            settings[key] = rows[0]["value"] if rows else ""
        api_key, base_url, model = settings["llm_api_key"], settings["llm_base_url"], settings["llm_model"]
        if not api_key:
            print("❌ 未配置 LLM API Key")
            return

    # 收集所有需要翻译的任务
    all_tasks = set()
    with open(DATA_DIR / "task_penetration.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            all_tasks.add(r["task"].strip())

    # 加载已有翻译
    existing = {}
    if OUTPUT.exists():
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))

    todo = [t for t in sorted(all_tasks) if t not in existing]
    print(f"总任务: {len(all_tasks)}, 已翻译: {len(existing)}, 待翻译: {len(todo)}")

    if not todo:
        print("✅ 全部已翻译")
        return

    # 构建调用函数
    if client_genai:
        gemini_model = args.model
        async def _translate(prompt: str) -> str:
            resp = await client_genai.aio.models.generate_content(
                model=gemini_model, contents=prompt,
                config={"temperature": 0},
            )
            return resp.text
    else:
        from openai import AsyncOpenAI
        oai = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120)
        async def _translate(prompt: str) -> str:
            resp = await oai.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], temperature=0,
            )
            return resp.choices[0].message.content

    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        numbered = "\n".join(f"{j+1}. {t}" for j, t in enumerate(batch))
        prompt = (
            f"将以下 {len(batch)} 条英文职业任务描述翻译为简洁的中文。"
            "每行一条，保持编号，只输出翻译结果，不要解释：\n\n" + numbered
        )

        for attempt in range(5):
            try:
                text = await _translate(prompt)
                lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
                for j, en in enumerate(batch):
                    if j < len(lines):
                        cn = lines[j].lstrip("0123456789.、) ").strip()
                        existing[en] = cn
                    else:
                        existing[en] = en  # fallback

                OUTPUT.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
                done = len(existing)
                total = len(all_tasks)
                print(f"  [{done}/{total}] 批次 {i//BATCH_SIZE + 1} 完成 ({len(batch)} 条)")
                await asyncio.sleep(1)  # 基础间隔，避免触发限流
                break
            except Exception as e:
                err = str(e)
                if ("429" in err or "RESOURCE_EXHAUSTED" in err or "503" in err) and attempt < 4:
                    wait = 15 * (attempt + 1)
                    print(f"  ⏳ 限流，等待 {wait}s 后重试 (attempt {attempt+1}/5)...")
                    await asyncio.sleep(wait)
                else:
                    print(f"  ❌ 批次 {i//BATCH_SIZE + 1} 失败: {e}")
                    OUTPUT.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"  已保存进度 ({len(existing)} 条)，重新运行可续翻")
                    return

    print(f"✅ 全部翻译完成: {len(existing)} 条")


if __name__ == "__main__":
    asyncio.run(main())

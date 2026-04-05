"""
端到端 LLM 调用测试 — 验证 Planner 能否真正通过 OpenAI 兼容格式调通 LLM。

用法:
    python scripts/test_e2e_llm.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm_client import LLMClient
from agent.planner import Planner
from agent.bootstrap import create_tool_registry


async def main():
    # --- 配置 ---
    api_key = sys.argv[1] if len(sys.argv) > 1 else ""
    base_url = sys.argv[2] if len(sys.argv) > 2 else "https://generativelanguage.googleapis.com/v1beta/openai/"
    model = sys.argv[3] if len(sys.argv) > 3 else "gemini-2.5-flash"

    if not api_key:
        import os
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("❌ 请提供 API Key: python scripts/test_e2e_llm.py <api_key> [base_url] [model]")
        sys.exit(1)

    print(f"🔧 配置:")
    print(f"   Base URL: {base_url}")
    print(f"   Model:    {model}")
    print()

    # --- Test 1: 直接调 LLMClient ---
    print("=" * 50)
    print("Test 1: LLMClient 直接调用")
    print("=" * 50)
    try:
        client = LLMClient(api_key=api_key, model=model, base_url=base_url)
        response = await client.chat([
            {"role": "user", "content": "用一句话介绍你自己"}
        ])
        print(f"✅ LLM 响应: {response[:200]}")
    except Exception as e:
        print(f"❌ LLMClient 调用失败: {e}")
        return

    print()

    # --- Test 2: Planner 生成执行计划 ---
    print("=" * 50)
    print("Test 2: Planner 生成执行计划")
    print("=" * 50)
    try:
        registry, _skill_loader = create_tool_registry()
        planner = Planner(
            tool_registry=registry,
            llm_client=client,
        )

        plan = await planner.plan("查看投递统计")
        print(f"✅ 生成计划: {len(plan.steps)} 个步骤")
        for i, step in enumerate(plan.steps):
            print(f"   步骤 {i+1}: [{step.tool_name}] {step.description}")
            if step.tool_args:
                print(f"           参数: {step.tool_args}")
    except Exception as e:
        print(f"❌ Planner 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return

    print()

    # --- Test 3: 更复杂的指令 ---
    print("=" * 50)
    print("Test 3: 复杂指令规划")
    print("=" * 50)
    try:
        plan2 = await planner.plan("帮我把字节跳动加入黑名单，然后查看统计数据")
        print(f"✅ 生成计划: {len(plan2.steps)} 个步骤")
        for i, step in enumerate(plan2.steps):
            print(f"   步骤 {i+1}: [{step.tool_name}] {step.description}")
            if step.tool_args:
                print(f"           参数: {step.tool_args}")
    except Exception as e:
        print(f"❌ 复杂指令规划失败: {e}")
        import traceback
        traceback.print_exc()

    print()
    print("🎉 端到端测试完成")


if __name__ == "__main__":
    asyncio.run(main())

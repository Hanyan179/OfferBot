"""
通用 Agent 对话测试脚本

通过 POST /api/test/chat 发送消息，收集完整执行过程，
自动分析返回结果并输出结构化测试报告。

用法:
    python scripts/test_agent_chat.py --message "帮我搜索上海 AI 岗位"
    python scripts/test_agent_chat.py --scenario all
    python scripts/test_agent_chat.py --scenario tool_chinese_name
    python scripts/test_agent_chat.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
SCENARIOS_FILE = Path(__file__).parent / "test_scenarios.json"


def load_scenarios() -> dict:
    """加载测试场景定义。"""
    if not SCENARIOS_FILE.exists():
        print(f"❌ 场景文件不存在: {SCENARIOS_FILE}")
        sys.exit(1)
    with SCENARIOS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f).get("scenarios", {})


def _is_chinese(text: str) -> bool:
    """检查文本是否包含中文字符。"""
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def send_message(
    base_url: str,
    message: str,
    conversation_id: str | None = None,
    history: list[dict] | None = None,
    timeout: float = 120.0,
) -> dict:
    """发送消息到测试接口，返回完整响应。"""
    payload: dict = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if history:
        payload["history"] = history

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{base_url}/api/test/chat", json=payload)
        resp.raise_for_status()
        return resp.json()


def check_result(result: dict, checks: dict) -> list[dict]:
    """根据检查规则验证结果，返回检查报告列表。"""
    reports: list[dict] = []

    if checks.get("has_reply"):
        passed = bool(result.get("reply"))
        reports.append({
            "check": "has_reply",
            "passed": passed,
            "detail": result.get("reply", "")[:100] if passed else "回复为空",
        })

    min_len = checks.get("min_reply_length")
    if min_len is not None:
        reply = result.get("reply", "")
        passed = len(reply) >= min_len
        reports.append({
            "check": "min_reply_length",
            "passed": passed,
            "detail": f"长度 {len(reply)}, 要求 >= {min_len}",
        })

    if checks.get("has_tool_calls"):
        tool_calls = result.get("tool_calls", [])
        passed = len(tool_calls) > 0
        names = [tc.get("name", "") for tc in tool_calls]
        reports.append({
            "check": "has_tool_calls",
            "passed": passed,
            "detail": f"调用了: {names}" if passed else "未调用任何 tool",
        })

    if checks.get("tool_display_name_is_chinese"):
        tool_calls = result.get("tool_calls", [])
        all_chinese = all(
            _is_chinese(tc.get("display_name", "")) for tc in tool_calls
        ) if tool_calls else False
        reports.append({
            "check": "tool_display_name_is_chinese",
            "passed": all_chinese,
            "detail": (
                [tc.get("display_name") for tc in tool_calls]
                if tool_calls
                else "无 tool 调用"
            ),
        })

    return reports


def run_scenario(base_url: str, name: str, scenario: dict) -> dict:
    """运行单个测试场景，返回场景报告。"""
    print(f"\n  📋 场景: {name} — {scenario.get('description', '')}")
    messages_def = scenario.get("messages", [])
    checks = scenario.get("checks", {})

    history: list[dict] = []
    last_result: dict = {}
    conversation_id: str | None = None

    for i, msg_def in enumerate(messages_def):
        msg = msg_def["message"]
        print(f"     [{i+1}/{len(messages_def)}] 发送: {msg[:50]}...")
        try:
            last_result = send_message(
                base_url, msg,
                conversation_id=conversation_id,
                history=history,
            )
            conversation_id = last_result.get("conversation_id") or conversation_id
            # 累积历史
            history.append({"role": "user", "content": msg})
            if last_result.get("reply"):
                history.append({"role": "assistant", "content": last_result["reply"]})
        except Exception as e:
            return {
                "scenario": name,
                "passed": False,
                "error": str(e),
                "checks": [],
            }

    check_reports = check_result(last_result, checks)
    all_passed = all(r["passed"] for r in check_reports)

    for r in check_reports:
        icon = "✅" if r["passed"] else "❌"
        print(f"     {icon} {r['check']}: {r.get('detail', '')}")

    return {
        "scenario": name,
        "passed": all_passed,
        "checks": check_reports,
        "reply_preview": (last_result.get("reply", "") or "")[:100],
        "tool_calls_count": len(last_result.get("tool_calls", [])),
        "total_duration_ms": last_result.get("total_duration_ms", 0),
    }


def main():
    parser = argparse.ArgumentParser(description="Agent 对话测试脚本")
    parser.add_argument("--message", "-m", help="单条消息测试")
    parser.add_argument("--scenario", "-s", help="场景名称，或 'all' 运行全部")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="服务地址")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式报告")
    args = parser.parse_args()

    if not args.message and not args.scenario:
        parser.print_help()
        sys.exit(1)

    base_url = args.base_url.rstrip("/")

    if args.message:
        print(f"🔧 单条消息测试: {args.message[:60]}...")
        try:
            result = send_message(base_url, args.message)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"  回复: {result.get('reply', '')[:200]}")
                print(f"  Tool 调用: {len(result.get('tool_calls', []))} 次")
                for tc in result.get("tool_calls", []):
                    print(f"    - {tc.get('name')} ({tc.get('display_name')}) "
                          f"{'✅' if tc.get('success') else '❌'} {tc.get('duration_ms')}ms")
                print(f"  总耗时: {result.get('total_duration_ms', 0)}ms")
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            sys.exit(1)
        return

    # 场景测试
    scenarios = load_scenarios()
    if args.scenario == "all":
        to_run = scenarios
    elif args.scenario in scenarios:
        to_run = {args.scenario: scenarios[args.scenario]}
    else:
        print(f"❌ 未知场景: {args.scenario}")
        print(f"   可用场景: {', '.join(scenarios.keys())}")
        sys.exit(1)

    print(f"🚀 运行 {len(to_run)} 个测试场景 (服务: {base_url})")
    reports: list[dict] = []
    for name, scenario in to_run.items():
        report = run_scenario(base_url, name, scenario)
        reports.append(report)

    # 汇总
    passed = sum(1 for r in reports if r["passed"])
    total = len(reports)
    print(f"\n{'='*50}")
    print(f"📊 结果: {passed}/{total} 通过")

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()

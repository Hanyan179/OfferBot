#!/bin/bash
# 实时监控 Agent 对话日志（自动跟踪新 turn 文件）
BASE="/Users/hansen/hansAi/boss-agent-workspace"
AGENT_LOGS="$BASE/boss-agent/data/logs"

echo "📋 Agent 对话日志监控"
echo "目录: $AGENT_LOGS"
echo "等待新对话..."
echo ""

last_file=""
last_size=0

while true; do
    newest=$(find "$AGENT_LOGS" -name "turn-*.log" -type f 2>/dev/null | xargs ls -t 2>/dev/null | head -1)
    if [ -n "$newest" ]; then
        if [ "$newest" != "$last_file" ]; then
            last_file="$newest"
            last_size=0
            echo ""
            echo "━━━ $(basename "$(dirname "$newest")")/$(basename "$newest") ━━━"
        fi
        current_size=$(wc -c < "$newest" 2>/dev/null || echo 0)
        if [ "$current_size" -gt "$last_size" ]; then
            tail -c +"$((last_size + 1))" "$newest"
            last_size=$current_size
        fi
    fi
    sleep 1
done

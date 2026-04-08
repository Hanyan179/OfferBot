#!/bin/bash
# OfferBot 开发环境启动脚本
# 一个 iTerm2 窗口，2行：上2列 + 下4列，共6个 pane
# 1. Kiro 对话（需求讨论）  2. Kiro 代码（代码修改）
# 3. 项目服务（uvicorn）    4. Agent 日志  5. getjob 日志  6. 命令行
#
# 用法:
#   ./start-dev.sh          全量启动（清理 + 重建 tmux + iTerm2 布局）
#   ./start-dev.sh attach   仅恢复 iTerm2 布局（attach 已有 tmux 会话）

BASE="/Users/hansen/hansAi/boss-agent-workspace"
GETJOB_DIR="$BASE/reference-crawler"
MODEL="claude-opus-4.6"
GETJOB_LOG="$GETJOB_DIR/target/logs/get-jobs.log"

SESSIONS=("OB-对话" "OB-代码" "OB-服务" "OB-日志" "OB-爬虫" "OB-终端")
DIRS=(
  "$BASE"
  "$BASE"
  "$BASE"
  "$BASE"
  "$BASE"
  "$BASE"
)
CMDS=(
  "cd $BASE && kiro-cli chat --model $MODEL"
  "cd $BASE && kiro-cli chat --model $MODEL"
  "cd $BASE && source .venv/bin/activate && cd boss-agent && python -m uvicorn web.app:app --host 0.0.0.0 --port 7860 --reload"
  "cd $BASE && exec bash scripts/tail-logs.sh"
  "tail -F $GETJOB_LOG 2>/dev/null || (echo '⚠️  等待 getjob 日志...' && while [ ! -f '$GETJOB_LOG' ]; do sleep 5; done && tail -F '$GETJOB_LOG')"
  "cd $BASE && source .venv/bin/activate && cd boss-agent && exec \$SHELL"
)

# ── attach 模式：只恢复 iTerm2 布局 ──
if [ "$1" = "attach" ]; then
  # 检查 tmux 会话是否存在
  MISSING=()
  for name in "${SESSIONS[@]}"; do
    tmux has-session -t "$name" 2>/dev/null || MISSING+=("$name")
  done
  if [ ${#MISSING[@]} -gt 0 ]; then
    echo "❌ 以下 tmux 会话不存在: ${MISSING[*]}"
    echo "   请先运行 ./start-dev.sh（不带参数）全量启动"
    exit 1
  fi
  echo "🔗 恢复 iTerm2 布局（attach 已有 tmux 会话）..."
  # 跳到 iTerm2 布局部分
  SKIP_TO_ITERM=true
fi

if [ "$SKIP_TO_ITERM" != "true" ]; then
# ── 1. 清理残留 ──
echo "🧹 清理残留会话..."
for name in "${SESSIONS[@]}"; do
  tmux has-session -t "$name" 2>/dev/null && tmux kill-session -t "$name" && echo "  killed: $name"
done

# 杀掉占用端口的进程
lsof -ti:7860 2>/dev/null | xargs kill -9 2>/dev/null

# ── 2. 启动 getjob 服务（如果未运行）──
if curl -s http://localhost:8888/api/health >/dev/null 2>&1; then
  echo "✅ getjob 服务已在运行 (port 8888)"
else
  echo "🚀 启动 getjob 服务..."
  cd "$GETJOB_DIR"
  nohup ./gradlew bootRun > /dev/null 2>&1 &
  GETJOB_PID=$!
  echo "  getjob PID: $GETJOB_PID，等待启动..."
  for i in $(seq 1 12); do
    sleep 5
    if curl -s http://localhost:8888/api/health >/dev/null 2>&1; then
      echo "  ✅ getjob 服务已启动 (${i}x5s)"
      break
    fi
    if [ $i -eq 12 ]; then
      echo "  ⚠️  getjob 启动超时，请手动检查"
    fi
  done
  cd "$BASE"
fi

# ── 3. 创建 tmux 会话 + 日志记录 ──
LOG_DIR="$BASE/data/logs/cli"
mkdir -p "$LOG_DIR"
TODAY=$(date +%Y-%m-%d)

echo "🚀 创建 tmux 会话..."
for i in "${!SESSIONS[@]}"; do
  name="${SESSIONS[$i]}"
  dir="${DIRS[$i]}"
  cmd="${CMDS[$i]}"
  SESSION_LOG_DIR="$LOG_DIR/$name"
  mkdir -p "$SESSION_LOG_DIR"
  tmux new-session -d -s "$name" -c "$dir" "$cmd"
  tmux pipe-pane -t "$name" -o 'perl -MPOSIX -e '\''
    my $dir = "'"$SESSION_LOG_DIR"'";
    my $cur = "";
    my $fh;
    while (<STDIN>) {
      my $today = strftime("%Y-%m-%d", localtime);
      if ($today ne $cur) {
        close $fh if $fh;
        open $fh, ">>", "$dir/$today.log" or die $!;
        $fh->autoflush(1);
        $cur = $today;
      }
      my $ts = strftime("[%H:%M:%S] ", localtime);
      print $fh $ts . $_;
    }
  '\'
  echo "  ✅ $name (日志: cli/$name/${TODAY}.log)"
done

fi  # end SKIP_TO_ITERM

# ── 4. iTerm2 窗口布局：上2 + 下4 ──
osascript <<'APPLESCRIPT'
tell application "iTerm2"
    activate
    delay 0.5
    set W to (create window with default profile)
    
    tell current tab of W
        -- session 1 = 上排左
        tell session 1
            set bottomLeft to (split horizontally with default profile)
        end tell
        -- 上排分2列
        tell session 1
            set topRight to (split vertically with default profile)
        end tell
        -- 下排分4列
        tell bottomLeft
            set botMid1 to (split vertically with default profile)
        end tell
        tell botMid1
            set botMid2 to (split vertically with default profile)
        end tell
        tell botMid2
            set botRight to (split vertically with default profile)
        end tell
        
        delay 1.5
        
        -- 上排左: Kiro 对话
        tell session 1
            write text "tmux attach -t 'OB-对话'"
        end tell
        delay 0.3
        -- 上排右: Kiro 代码
        tell topRight
            write text "tmux attach -t 'OB-代码'"
        end tell
        delay 0.3
        -- 下排1: 项目服务
        tell bottomLeft
            write text "tmux attach -t 'OB-服务'"
        end tell
        delay 0.3
        -- 下排2: Agent 日志
        tell botMid1
            write text "tmux attach -t 'OB-日志'"
        end tell
        delay 0.3
        -- 下排3: getjob 日志
        tell botMid2
            write text "tmux attach -t 'OB-爬虫'"
        end tell
        delay 0.3
        -- 下排4: 命令行
        tell botRight
            write text "tmux attach -t 'OB-终端'"
        end tell
    end tell
end tell
APPLESCRIPT

echo ""
echo "✅ OfferBot 开发环境已启动 (模型: $MODEL)"
echo "  工作目录: $BASE"
echo "  ┌──────────────┬──────────────┐"
echo "  │ OB-对话      │ OB-代码      │"
echo "  │ (需求讨论)   │ (代码修改)   │"
echo "  ├──────┬──────┬──────┬────────┤"
echo "  │OB-服务│OB-日志│OB-爬虫│OB-终端│"
echo "  │uvicorn│agent │getjob│ shell │"
echo "  └──────┴──────┴──────┴────────┘"
echo ""
echo "服务地址: http://localhost:7860 (OfferBot)"
echo "         http://localhost:8888 (getjob)"
echo "📝 对话日志: data/logs/cli/{session}/${TODAY}.log"
echo "📋 Agent日志: boss-agent/data/logs/{session}/turn-*.log"
echo "📋 getjob日志: reference-crawler/target/logs/get-jobs.log"

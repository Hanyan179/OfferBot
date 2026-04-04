# 并行开发协调文件

## 说明

本文件用于协调多个 Kiro 实例并行开发时的文件冲突。

**每个 Kiro 在开始工作前必须**：
1. 读取本文件，了解其他分支正在改哪些文件
2. 如果自己要改的文件跟其他分支有重叠，需要特别注意合并冲突
3. 完成工作后更新本文件（在自己的分支上 commit），记录自己改了哪些文件

**重要**：本文件通过 git 追踪，所有 worktree 共享同一个 `.git`，所以每个分支都能读到最新版本。
但因为各分支独立 commit，更新本文件后需要其他分支 `git merge` 或 `git checkout main -- PARALLEL-WORK.md` 来同步。

## Worktree 布局

所有目录位于 `~/hansAi/` 下：

| 目录 | 分支 | 用途 | Kiro 窗口 |
|------|------|------|----------|
| `boss-agent-workspace` | main | 原始仓库（不直接开发） | — |
| `boss-agent-branch-1` | branch-1 | Kiro 1 开发区 | 简历编辑与导出 |
| `boss-agent-branch-2` | branch-2 | Kiro 2 开发区 | 待分配 |
| `boss-agent-branch-3` | branch-3 | Kiro 3 开发区 | 待分配 |
| `boss-agent-branch-4` | branch-4 | Kiro 4 开发区 | 待分配 |
| `boss-agent-merge` | merge-zone | 合并区域 | 手动合并用 |

## 合并流程

```bash
cd ~/hansAi/boss-agent-merge
git merge branch-1
git merge branch-2   # 如有冲突手动解决
git merge branch-3
git merge branch-4
# 全部合并完成后
git checkout main
git merge merge-zone
git push origin main
```

## 分支工作记录

### Branch-1: 简历编辑与导出（resume-edit-export）

**状态**: 进行中
**Spec**: `.kiro/specs/resume-edit-export/`

**预计涉及文件**:
| 操作 | 文件 | 冲突风险 |
|------|------|---------|
| 新建 | `boss-agent/web/resume_service.py` | 无 |
| 修改 | `boss-agent/web/app.py` | ⚠️ 中（新增路由） |
| 修改 | `boss-agent/web/templates/memory_content.html` | ⚠️ 中 |
| 新建 | `boss-agent/tests/test_resume_service_pbt.py` | 无 |
| 新建 | `boss-agent/tests/test_resume_api.py` | 无 |
| 修改 | `boss-agent/requirements.txt` | ⚠️ 低（加 python-docx） |

### Branch-2: （待分配）

**状态**: 空闲
**预计涉及文件**: 待定

### Branch-3: （待分配）

**状态**: 空闲
**预计涉及文件**: 待定

### Branch-4: （待分配）

**状态**: 空闲
**预计涉及文件**: 待定

## 高冲突风险文件（多分支可能同时修改）

以下文件是多个功能可能同时修改的"热点文件"，分配任务时尽量避免多分支同时改：

| 文件 | 说明 | 当前被哪个分支修改 |
|------|------|-------------------|
| `boss-agent/web/app.py` | FastAPI 主应用，新增路由 | Branch-1 |
| `boss-agent/agent/bootstrap.py` | Tool 注册入口 | — |
| `boss-agent/agent/system_prompt.py` | System Prompt | — |
| `boss-agent/config.py` | 全局配置 | — |
| `boss-agent/db/schema.sql` | 数据库 Schema | — |
| `boss-agent/requirements.txt` | Python 依赖 | Branch-1 |
| `boss-agent/web/templates/base.html` | 基础模板 | — |
| `boss-agent/web/templates/index.html` | 主页模板 | — |

## Kiro 工作规范

每个 Kiro 实例在开始任何文件修改前，必须执行以下检查：

1. **读取本文件** — 确认自己要改的文件没有被其他分支占用
2. **只改自己分支的文件** — 不要跨分支修改文件
3. **新建文件优先** — 尽量把逻辑放在新文件里，减少对共享文件的修改
4. **追加优先** — 修改共享文件时，改动尽量集中在文件末尾（追加而非插入），减少冲突概率
5. **完成后更新本文件** — 记录实际修改了哪些文件，标记状态为"已完成"

# 并行开发协调文件

## 说明

本文件用于协调多个 Kiro 实例并行开发时的文件冲突。

**每个 Kiro 在开始工作前必须**：
1. 读取本文件，了解其他分支正在改哪些文件
2. 如果自己要改的文件跟其他分支有重叠，需要特别注意合并冲突
3. 完成工作后更新本文件，记录实际修改了哪些文件

## Worktree 布局

所有目录位于 `~/hansAi/` 下，每个 Kiro 打开对应目录，能看到完整项目，但只在自己分支上 commit：

| 目录 | 分支 | 任务 |
|------|------|------|
| `boss-agent-workspace` | branch-1 | 简历编辑与导出（resume-edit-export） |
| `boss-agent-branch-2` | branch-2 | 待分配 |
| `boss-agent-branch-3` | branch-3 | 待分配 |
| `boss-agent-branch-4` | branch-4 | 待分配 |
| `boss-agent-merge` | merge-zone | 合并区域（手动合并用） |

## 合并流程

```bash
cd ~/hansAi/boss-agent-merge
git merge branch-1
git merge branch-2
git merge branch-3
git merge branch-4
# 全部合并完成后
git checkout main
git merge merge-zone
git push origin main
```

## 分支工作记录

### Branch-1（boss-agent-workspace）: 简历编辑与导出

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

### Branch-2（boss-agent-branch-2）: 待分配

**状态**: 空闲

### Branch-3（boss-agent-branch-3）: 待分配

**状态**: 空闲

### Branch-4（boss-agent-branch-4）: 待分配

**状态**: 空闲

## 高冲突风险文件

以下文件是多个功能可能同时修改的"热点文件"，分配任务时尽量避免多分支同时改：

| 文件 | 说明 | 当前被哪个分支修改 |
|------|------|-------------------|
| `boss-agent/web/app.py` | FastAPI 主应用 | Branch-1 |
| `boss-agent/agent/bootstrap.py` | Tool 注册入口 | — |
| `boss-agent/agent/system_prompt.py` | System Prompt | — |
| `boss-agent/config.py` | 全局配置 | — |
| `boss-agent/db/schema.sql` | 数据库 Schema | — |
| `boss-agent/requirements.txt` | Python 依赖 | Branch-1 |
| `boss-agent/web/templates/base.html` | 基础模板 | — |
| `boss-agent/web/templates/index.html` | 主页模板 | — |

## Kiro 工作规范

1. **读取本文件** — 开始前确认自己要改的文件没有被其他分支占用
2. **只在自己分支 commit** — 可以读所有文件，但只改自己负责的
3. **新建文件优先** — 尽量把逻辑放在新文件里，减少共享文件修改
4. **追加优先** — 修改共享文件时，改动集中在文件末尾
5. **完成后更新本文件** — 记录实际修改了哪些文件

---
name: 猎聘岗位采集与投递
description: 通过 getjob 服务控制猎聘平台的岗位搜索、爬取、匹配分析和精准投递
when_to_use: 当用户需要搜索岗位、爬取数据、投递简历、查看投递进度时
memory_categories: [job_sprint_goals, career_planning, key_points]
allowed-tools: [getjob_service_manage, platform_status, platform_start_task, platform_stop_task, platform_get_config, platform_update_config, sync_jobs, platform_stats, query_jobs, get_user_profile, get_memory]
---

## 场景描述

用户需要在猎聘平台搜索岗位、爬取数据、或投递简历。所有浏览器操作由 getjob 服务（Java）执行，AI 通过 HTTP API 控制。AI 负责决策和编排，getjob 负责执行。

## 核心原则

1. **每一步都要检查状态**：调用任何 Tool 后，必须检查返回的 success 字段
2. **失败时不要卡死**：如果某步失败，告诉用户原因，给出解决建议，等用户反馈后再继续
3. **用户确认优先**：投递前必须让用户确认，不要自动投递
4. **岗位链接很重要**：推荐岗位时一定要附上猎聘链接，用户可以直接点击查看详情

## 前置检查流程（每次操作前必须执行）

### 第一步：检查 getjob 服务是否在运行

调用 `getjob_service_manage(action="check")`

- **未运行**（running = false）：
  → 调用 `getjob_service_manage(action="start")` 自动启动
  → 启动成功后告诉用户："getjob 服务已启动，浏览器已打开，请在浏览器中用微信扫码登录猎聘"
  → 如果启动失败，告诉用户错误原因
  → **等待用户确认登录完成**

- **已运行**（running = true）：
  → 继续下一步

### 第二步：检查猎聘登录状态

调用 `platform_status(platform="liepin")`

## 场景 A：搜索并爬取岗位（只爬不投）

用户说"帮我搜岗位"、"找一下上海的 AI 岗位"等。

### 执行步骤

1. **前置检查**（见上方流程）

2. **获取搜索条件**
   - 调用 `get_user_profile()` 检查用户画像
   - 有画像 → 从 target_cities、target_roles、salary_min/max 提取条件
   - 无画像 → 从对话中提取，信息不足就问用户
   - 调用 `get_memory(category="job_sprint_goals")` 补充近期目标
   - 用户明确说的条件 **优先级最高**

3. **配置 getjob 为仅爬取模式**
   ```
   platform_update_config(platform="liepin", config={
     "keywords": "[\"AI工程师\",\"Python后端\"]",
     "city": "上海",
     "salaryCode": "15$30",
     "scrapeOnly": true    ← 关键：只爬不投
   })
   ```
   - 检查返回 success=true
   - 如果失败，告诉用户配置更新失败的原因

4. **向用户确认搜索条件**
   - "我准备在猎聘搜索：关键词【AI工程师、Python后端】，城市【上海】，薪资【15-30K】。要调整吗？"
   - 等用户确认

5. **启动爬取任务**
   ```
   platform_start_task(platform="liepin")
   ```
   - 检查返回 success=true
   - 告诉用户："爬取任务已启动，你可以继续跟我聊天"

6. **用户问进度时**
   ```
   platform_stats(platform="liepin")
   ```
   - 返回已爬取数量、按城市/行业分布等

7. **爬取完成后同步数据**
   - 先检查 `platform_status` 确认 isRunning=false
   ```
   sync_jobs(platform="liepin")
   ```
   - 告诉用户："爬取完成，新增 XX 条岗位，更新 XX 条"

## 场景 B：投递岗位

用户说"帮我投递"、"投前 5 个"等。

### 执行步骤

1. **前置检查**

2. **配置 getjob 为投递模式**
   ```
   platform_update_config(platform="liepin", config={
     "scrapeOnly": false    ← 关键：开启投递
   })
   ```

3. **确认投递**
   - "我将启动猎聘投递任务，会对搜索到的岗位自动发送打招呼消息。确认开始吗？"
   - **必须等用户确认**

4. **启动投递任务**
   ```
   platform_start_task(platform="liepin")
   ```

5. **投递完成后**
   - 同步数据到本地
   - 汇报投递结果

## 场景 C：查看投递状态

用户说"投递情况怎么样"、"进度如何"等。

```
platform_status(platform="liepin")   → 任务是否在运行
platform_stats(platform="liepin")    → 统计数据
```

组合两个结果，用自然语言汇报。

## 场景 D：停止任务

用户说"停止"、"别投了"等。

```
platform_stop_task(platform="liepin")
```

## 错误处理

| 错误情况 | AI 应该做什么 |
|---------|-------------|
| getjob 服务不可达 | 告诉用户启动 getjob，等用户反馈 |
| 未登录 | 引导用户扫码登录，等用户反馈后再次检查 |
| 任务已在运行 | 问用户要等还是停止 |
| 配置更新失败 | 告诉用户具体错误，尝试重新配置 |
| 启动任务失败 | 告诉用户错误原因，建议检查 getjob 日志 |
| 同步数据失败 | 告诉用户，建议稍后重试 |

## 注意事项

- 猎聘的打招呼语由猎聘 App 设置，程序无法修改。如果用户想改打招呼语，告诉他在猎聘 App 中设置
- 猎聘默认打招呼无上限，但主动发消息有上限
- 不要在一次对话中反复启动任务，注意平台风控
- 每次操作前都要检查状态，不要假设上一步的状态还有效
- 用户画像中的条件是参考，用户当前说的话永远优先

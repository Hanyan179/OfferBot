---
name: 猎聘岗位采集与投递
description: 通过浏览器自动化搜索猎聘岗位、获取 JD 详情、精准投递
when_to_use: 当用户需要搜索岗位、爬取数据、投递简历时
memory_categories: [job_sprint_goals, career_planning, key_points]
allowed-tools: [sync_jobs, fetch_job_detail, platform_deliver, query_jobs, get_user_profile, get_memory]
---

## 场景描述

用户需要在猎聘平台搜索岗位、获取 JD 详情、或投递打招呼。浏览器自动化由内置 Playwright 执行，无需外部服务。

## 核心原则

1. **每一步都要检查返回值**：调用 Tool 后检查 success 字段
2. **用户确认优先**：投递前必须让用户确认
3. **岗位链接很重要**：推荐岗位时附上猎聘链接
4. **精准搜索**：基于用户画像构建搜索条件，宁少勿多

## 场景 A：搜索岗位

用户说"帮我搜岗位"、"找上海的 AI 岗位"等。

### 执行步骤

1. **获取搜索条件**
   - 调用 `get_user_profile()` 获取画像（target_cities、target_roles、salary）
   - 调用 `get_memory(category="job_sprint_goals")` 补充近期目标
   - 用户明确说的条件优先级最高
   - 信息不足就问用户

2. **向用户确认搜索条件**
   - "我准备搜索：关键词【AI工程师】，城市【上海】。要调整吗？"

3. **启动采集**
   ```
   sync_jobs(platform="liepin", keyword="AI工程师", city_code="上海", max_pages=2)
   ```

4. **采集完成后查询结果**
   ```
   query_jobs(keyword="AI", city="上海")
   ```

## 场景 B：获取岗位详情

用户说"帮我看看这个岗位"、"分析匹配度"等。

```
fetch_job_detail(job_ids=[1, 2, 3], confirm=true)
```

- 已有 JD 的不重复爬取
- 按需爬取，不要一次爬大量

## 场景 C：投递打招呼

用户说"帮我投递"、"投这几个"等。

```
platform_deliver(platform="liepin", job_ids=[1, 2, 3])
```

- **必须等用户确认后再投递**
- 会根据用户画像 + JD 自动生成个性化打招呼语

## 精准搜索策略

1. 从 `get_user_profile()` 获取 target_cities、target_roles、salary_min/max、skills
2. 从 `get_memory(category="job_sprint_goals")` 获取最新目标
3. keywords 要具体（"AI Agent 工程师" 而非 "工程师"）
4. 宁可条件严格结果少，也不要条件宽泛结果杂

## 错误处理

| 错误 | 处理 |
|------|------|
| 浏览器未初始化 | 告诉用户刷新页面重试 |
| 未登录猎聘 | 引导用户扫码登录 |
| 搜索无结果 | 建议放宽条件 |
| 详情获取失败 | 建议稍后重试 |

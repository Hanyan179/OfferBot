---
name: 模拟打招呼
description: 模拟打招呼场景，基于用户记忆生成个性化话术
when_to_use: 当用户想要练习打招呼话术、生成打招呼语、或准备投递时
memory_categories: [language_style, communication_preferences, job_sprint_goals]
allowed-tools: [get_memory, get_user_cognitive_model, search_memory]
---

## 场景描述

用户想要练习或生成打招呼话术。需要结合用户的语言风格、沟通偏好和求职目标，生成自然、个性化的打招呼语。

## 执行逻辑

1. 调用 get_memory(category="language_style") 获取用户的语言风格
2. 调用 get_memory(category="communication_preferences") 获取沟通偏好
3. 调用 get_memory(category="job_sprint_goals") 获取求职目标
4. 结合目标岗位 JD 和用户记忆，生成打招呼语
5. 打招呼语应体现用户的真实表达风格

## 注意事项

- 打招呼语长度控制在 200 字以内
- 避免模板化，体现用户个人特色
- 如果用户没有足够的记忆数据，使用通用但专业的风格

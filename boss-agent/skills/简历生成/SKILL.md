---
name: 简历生成
description: 基于用户记忆和简历数据生成个性化 DOCX 简历
when_to_use: 当用户需要生成或优化简历时
memory_categories: [career_planning, key_points, language_style, personality_traits]
allowed-tools: [get_memory, get_user_cognitive_model, search_memory]
---

## 场景描述

用户需要生成或优化简历。结合数据库中的结构化简历数据和记忆系统中的软性信息（职业规划、核心亮点、语言风格等），生成更贴合用户真实情况的简历内容。

## 执行逻辑

1. 调用 get_user_cognitive_model() 获取完整用户画像
2. 调用 get_memory(category="career_planning") 获取职业规划
3. 调用 get_memory(category="key_points") 获取核心亮点和要点信息
4. 调用 get_memory(category="language_style") 获取语言风格偏好
5. 结合简历结构化数据，生成个性化简历内容
6. 确保简历内容反映用户的真实特点和表达习惯

## 注意事项

- 简历内容应基于事实，不虚构经历
- 语言风格与用户日常表达保持一致
- 突出用户记忆中提到的核心亮点和差异化优势

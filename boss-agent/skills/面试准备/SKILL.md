首先---
name: 面试准备
description: 基于用户记忆和岗位信息提供个性化面试准备建议
when_to_use: 当用户需要准备面试、模拟面试问答、或了解面试技巧时
memory_categories: [key_points, personal_thoughts, career_planning, hobbies_interests]
allowed-tools: [get_memory, get_user_cognitive_model, search_memory]
---

## 场景描述

用户即将参加面试，需要针对性的准备建议。结合用户的技术要点、项目经验细节、个人想法和职业规划，提供基于用户真实经验的面试建议。

## 执行逻辑

1. 调用 get_user_cognitive_model() 获取完整用户画像
2. 调用 get_memory(category="key_points") 获取技术要点和项目经验
3. 调用 get_memory(category="personal_thoughts") 获取个人想法和观点
4. 调用 get_memory(category="career_planning") 获取职业规划
5. 结合目标岗位 JD，生成针对性的面试准备建议
6. 包括常见问题的个性化回答建议

## 注意事项

- 面试建议应基于用户的真实经验，不编造
- 帮助用户梳理项目经历中的亮点和难点
- 针对不同类型面试（技术面、HR 面、项目面）提供差异化建议

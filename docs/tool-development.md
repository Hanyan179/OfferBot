# 开发新 Tool

OfferBot 的能力通过 Tool 扩展。每个 Tool 是一个 Python 类，继承 `Tool` 基类，注册后模型自动就会调用。

## 4 步流程

### 1. 创建 Tool 类

在 `boss-agent/tools/` 下新建文件，继承 `Tool`：

```python
from typing import Any
from agent.tool_registry import Tool

class MyTool(Tool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "这个 Tool 做什么"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询内容"},
            },
            "required": ["query"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        query = params["query"]
        # 你的逻辑
        return {"result": f"处理了: {query}"}
```

### 2. 注册到 bootstrap

编辑 `agent/bootstrap.py`，导入并注册：

```python
from tools.my_tool import MyTool

def create_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    # ... 已有的 tools
    registry.register(MyTool())
    return registry
```

### 3. 更新 System Prompt

在 `agent/system_prompt.py` 中添加使用场景说明，让模型知道什么时候该调用这个 Tool。

### 4. 测试

模型会根据对话上下文自动决定是否调用你的 Tool。启动后直接对话测试即可。

## Tool 基类接口

| 属性/方法 | 必须实现 | 说明 |
|-----------|---------|------|
| `name` | ✅ | 唯一名称，用于 function calling |
| `description` | ✅ | 功能描述，模型据此决定是否调用 |
| `parameters_schema` | ✅ | JSON Schema 格式的参数定义 |
| `execute(params, context)` | ✅ | 异步执行方法 |
| `category` | 可选 | 分类，默认 `"general"` |
| `is_concurrency_safe` | 可选 | 是否可并发，默认 `False` |

## context 对象

`execute` 的 `context` 参数包含：

- `context["db"]` — 数据库连接（`Database` 实例）
- 其他上下文信息根据 Agent 运行时注入

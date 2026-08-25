# 本项目 Python 速成（Java/Spring 开发者专用）

> 目的：看完本笔记，再读本项目的 `.py` 文件在**语法层面**不至于卡壳。
> 只覆盖本项目真实出现的 Python 特性，不灌水。学习时**对照身边代码看**效果最好。

## 0. 心态：把 type hint 当提示卡，别当强制约束

Python 的类型注解（`List` / `Dict` / `Optional`）**运行时不做检查**，只是给 IDE 和阅读者看的"提示"。
所以你可以把它当 Java 的泛型/类型声明，但**不强制**。

| 你熟（Java） | 本项目 Python |
|---|---|
| `List<String>` | `List[str]` / `list` |
| `Map<String,Object>` | `Dict[str, Any]` / `dict` |
| `Optional<String>` | `Optional[str]` / `str \| None` |
| `new HashMap<>()` | `{}` |
| `String s = "a"` | `s = "a"`（无类型声明） |
| lambda | `lambda x: x + 1`，更常用列表推导 |
| `null` | `None` |

## 1. async / await（本项目最大的一道坎，必懂）

异步 ≠ 多线程。它是"I/O 等待时不阻塞线程"。

- `async def f(): ...` ：定义异步函数，函数体里通常要 `await` 某个慢操作（LLM、DB、HTTP、MCP）。
- `await x` ：**等待 x 完成并取回结果**，期间让出控制权。Java 类比 `future.join()`（但不阻塞线程）。
- 调一个 `async def` 函数**必须 `await`**，否则拿到的是"协程对象"不执行。
- `async for ... in ...` ：迭代一个异步流，每次循环的元素可能要等一会。对应 SSE 流式、LLM 逐字输出。

本项目高频三句：
```python
decision = await chain.ainvoke({...})   # await 调 LLM
await mcp_client.get_tools()            # await 连 MCP 服务
async for event in graph.astream(...):  # 流式逐条拿结果
```

## 2. 类型注解 + typing

- `List[str]` 字符串列表；`Dict[str, Any]` key为str、value任意；`Any`=不管类型。
- `Optional[str]` == `str | None`（本项目两者混用）。
- `TypedDict`：声明一个"长怎样的字典"，比裸 dict 结构化。对应一个用字典实现的 DTO，但返回时通常是 `{...}` 字面量。

## 3. `Annotated[X, reducer]` + `operator.add`（State 合并机制核心）

```python
import operator
routing: Annotated[List[Dict], operator.add]
```
- `Annotated[X, tag]` = "在类型 X 上挂便利贴 tag"。tag 不运行，只是框架读取。
- `operator.add` = 内置加法函数，用于 list 即"拼接"。
- **LangGraph 约定**：字段声明 `Annotated[List, f]` 时，多个节点往它"加东西"不会覆盖，而是调用 `f` 合并。`operator.add` ⇒ **追加**。

为什么需要：多个专家**并行**都往同一字段追加，直接改同一个 list 会冲突。用 reducer，LangGraph 能安全拼接。

面试话术：
> "LangGraph 的 State 字段用 `Annotated[类型, reducer]` 声明合并策略；`operator.add` 表示追加而非覆盖，并行节点往同一字段添加时不互相覆盖，是并行安全的关键。"

自定义 reducer 见 `app/agent/multi_agent/state.py` 的 `merge_errors`：接收 `(current, incoming)` 返回合并结果。

## 4. Pydantic（数据模型与校验，对应 DTO + Bean Validation）

```python
from pydantic import BaseModel, Field
class RouteDecision(BaseModel):
    specialists: List[str] = Field(description="...")
    reason: str = Field(description="...")
```
- 继承 `BaseModel` 定义数据模型，对应 Java `@Data class`。
- 关键用法：`llm.with_structured_output(RouteDecision)` 让 LLM 按该类定义的 JSON 结构输出，Pydantic 自动反序列化。对应 `ObjectMapper.readValue(json, RouteDecision.class)`。
- 于是代码里可直接 `decision.specialists` 取字段。这就是"让 LLM 输出结构化 JSON"的标准姿势。

## 5. 一眼看懂的一行惯用法

```python
text = A if flag else B                  # Java: flag ? A : B
specialists = [s for s, _ in pairs]      # 列表推导 / Java stream map
valid = [p for p in pairs if p in set]   # 过滤 / Java stream filter
val = state.get("key", "默认")            # dict 取值，缺省给默认
spec = state.get("k") or "默认"           # None/空则给默认
f"会话 {id} 请求: {q[:100]}"              # f-string 字符串插值
for s, t in zip(specialists, tasks):     # 两列表按位置配对
```

## 6. 单例：模块级变量

```python
# config.py 末尾
config = Settings()        # import 一次全局共享
```
到处 `from app.config import config` 拿到**同一个对象**。对应 Java `@Component` / static 单例。

## 7. 综合自测（读真实代码）

```python
async def run(self, state):
    user_input = state.get("specialist_task") or state.get("user_input", "")
    working_state = dict(state)                    # 浅拷贝，避免污染原对象
    if user_input:
        memory_context = await asearch_memory(query=user_input, limit=3)  # 异步查记忆
        if memory_context:
            working_state["user_input"] = f"{user_input}\n\n{memory_context}"
    result = await self._execute(working_state)    # 调子类真正干活
    result.setdefault("status", "success")         # 缺 status 则补 "success"
    return result
```

## 8. 下一步

看懂本笔记后，回到 `docs/` 或 `README.md`，按模块精读。此时语法不再阻塞你，
专注理解"数据流 + 架构设计"（这就是练习的核心)。

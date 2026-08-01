# Multi-Agent Routing & Orchestration Reference

> Research collected from Anthropic, OpenAI, LangChain, academic papers, and production systems.
> Compiled for the OnCall-Agent project — which already implements a Supervisor + Specialist pattern.

---

## 1. Key Blog Posts & Articles

### 1.1 Anthropic — "Building Effective Agents" (Dec 2024)

**URL**: https://www.anthropic.com/engineering/building-effective-agents
**Authors**: Erik S., Barry Zhang (Anthropic)

The single most important reference for agent design. Key takeaways:

**Core principle**: *"The most successful implementations use simple, composable patterns rather than complex frameworks."*

**Distinction: Workflows vs Agents**
- **Workflows**: LLMs and tools orchestrated through *predefined* code paths
- **Agents**: LLMs *dynamically* direct their own processes and tool usage

**5 Workflow Patterns (from simplest to most complex)**:

| # | Pattern | Description | When to Use |
|---|---------|-------------|-------------|
| 1 | **Prompt Chaining** | Steps execute sequentially; each LLM call processes the previous output | Task decomposes into fixed subtasks; trade latency for accuracy |
| 2 | **Routing** | Classify input → direct to specialized follow-up | Complex tasks with distinct categories (customer support tiers, model selection by difficulty) |
| 3 | **Parallelization** | LLMs work simultaneously; outputs aggregated programmatically | Sectioning (independent subtasks) or Voting (multiple perspectives for confidence) |
| 4 | **Orchestrator-Workers** | Central LLM dynamically breaks down tasks, delegates to workers, synthesizes results | Can't predict subtasks in advance (e.g., multi-file code changes) |
| 5 | **Evaluator-Optimizer** | One LLM generates response; another evaluates in a loop | Clear evaluation criteria; iterative refinement adds measurable value |

**Autonomous Agent Pattern**: LLM uses tools in a loop, gaining "ground truth" from environment at each step. Best for open-ended problems where steps can't be predicted.

**Three Core Principles**:
1. Maintain simplicity in agent design
2. Prioritize transparency — explicitly show planning steps
3. Carefully craft your Agent-Computer Interface (ACI) — invest as much in tool documentation as you would in HCI

**Practical advice for your project**: Your existing Plan-Execute-Replan is the Orchestrator-Workers pattern. Your Supervisor + Specialists is the Routing pattern. Anthropic recommends starting with the simpler pattern and adding complexity only when it measurably helps.

---

### 1.2 LangChain — "LangGraph: Multi-Agent Workflows" (Jan 2024)

**URL**: https://blog.langchain.dev/langgraph-multi-agent-workflows/

Defines three multi-agent architectures with code examples:

**Pattern 1: Multi-Agent Collaboration (Shared Scratchpad)**
- All agents share a single message scratchpad — every step visible to all
- Rule-based router: if tool invoked → call tool; if "FINAL ANSWER" → return to user; else → next agent
- **Pro**: Full transparency; agents can build on each other's work
- **Con**: Verbose; passes all intermediate steps even when only final answer matters
- **Notebook**: `examples/multi_agent/multi-agent-collaboration.ipynb`

**Pattern 2: Agent Supervisor**
- Supervisor LLM routes to specialist agents; each has independent scratchpad
- Only final responses are appended to global scratchpad
- Supervisor = "an agent whose tools are other agents"
- **Notebook**: `examples/multi_agent/agent_supervisor.ipynb`
- **This is closest to your current architecture**

**Pattern 3: Hierarchical Agent Teams**
- Agents in nodes are themselves LangGraph objects (nested graphs)
- Supervisor coordinates teams of sub-graphs
- **Notebook**: `examples/multi_agent/hierarchical_agent_teams.ipynb`

**Key insight**: Each agent can have its own prompt, LLM, tools, and custom code. Control flow via edges; communication via graph state.

**Comparison to other frameworks**:
- **AutoGen**: Frames multi-agent as "conversation"; LangGraph uses "graph" framing for better control of transition probabilities
- **CrewAI**: Higher-level; LangGraph gives more low-level controllability

---

### 1.3 OpenAI — "New Tools for Building Agents" (Mar 2025)

**URL**: https://openai.com/index/new-tools-for-building-agents/

Announces the **Agents SDK** and **Responses API**:

**Key components**:
- **Responses API**: Combines Chat Completions simplicity with Assistants API tool-use
- **Built-in tools**: Web search, file search, computer use
- **Agents SDK**: Open-source, orchestrates single-agent and multi-agent workflows

**Agents SDK Design**:
```python
triage_agent = Agent(
    name="Triage Agent",
    instructions="Route the user to the correct agent.",
    handoffs=[shopping_agent, support_agent],
)
```

**Key features**:
- **Agents**: Configurable LLMs with instructions + built-in tools
- **Handoffs**: Intelligently transfer control between agents
- **Guardrails**: Input/output validation
- **Tracing & Observability**: Visualize agent execution traces

**Real product examples**:
- **Coinbase**: Used Agents SDK to prototype AgentKit (crypto wallet interactions)
- **Box**: Agents that search internal data + public web
- **Navan**: AI-powered travel agent using file search for RAG
- **Hebbia**: Web search for financial research
- **Unify**: Computer use for go-to-market automation

---

### 1.4 LangChain — LangGraph Multi-Agent Concepts

**URL**: https://langchain-ai.github.io/langgraph/concepts/multi_agent/

Official conceptual documentation for multi-agent patterns in LangGraph.

---

## 2. Relevant Papers

### 2.1 AutoGen (Microsoft, Aug 2023)

**Paper**: https://arxiv.org/abs/2308.08155
**GitHub**: https://github.com/microsoft/autogen

- Framework for multi-agent conversation
- Agents are customizable, conversable, operate in various modes (LLMs + human + tools)
- Both natural language and code used to program conversation patterns
- Generic infrastructure for diverse applications: math, coding, QA, operations research, decision-making

**Key architectural idea**: Frame multi-agent coordination as *conversational turns* rather than graph transitions. Agents "converse" to accomplish tasks.

---

### 2.2 CodeAct (ICML 2024)

**Paper**: https://arxiv.org/abs/2402.01030
**GitHub**: https://github.com/xingyaoww/code-act

- Proposes executable Python code as a *unified action space* for LLM agents
- Outperforms JSON/text-based actions by up to 20% success rate
- Agent can dynamically revise actions based on new observations
- Integrated with Python interpreter for multi-turn interaction

**Relevance**: Shows that unified action spaces matter — consider whether your specialists should share a common action format.

---

### 2.3 Additional Notable Papers

| Paper | URL | Key Contribution |
|-------|-----|------------------|
| **ReAct** (Yao et al., 2022) | https://arxiv.org/abs/2210.03629 | Reasoning + Acting interleaved; basis for your Chat Agent |
| **Plan-and-Solve** (Wang et al., 2023) | https://arxiv.org/abs/2305.04091 | Improved planning via zero-shot CoT; basis for Plan-Execute |
| **SWE-agent** (Yang et al., 2024) | https://arxiv.org/abs/2405.15793 | Agent design for software engineering; ACI design principles |
| **MetaGPT** (Hong et al., 2023) | https://arxiv.org/abs/2308.00352 | Multi-agent with SOPs (Standard Operating Procedures); role assignment |
| **CAMEL** (Li et al., 2023) | https://arxiv.org/abs/2303.17760 | Communicative agents for "mind exploration"; role-play framework |

---

## 3. GitHub Repos with Good Examples

### 3.1 LangGraph Multi-Agent Examples (YOUR STACK)

**URL**: https://github.com/langchain-ai/langgraph/tree/main/examples/multi_agent

| File | Pattern | Description |
|------|---------|-------------|
| `multi-agent-collaboration.ipynb` | Shared scratchpad | Agents see all intermediate steps |
| `agent_supervisor.ipynb` | Supervisor routing | LLM supervisor routes to specialists |
| `hierarchical_agent_teams.ipynb` | Nested graphs | Teams of agents organized hierarchically |

### 3.2 OpenAI Agents SDK

**URL**: https://github.com/openai/openai-agents-python

- Handoffs between agents (triage → specialist)
- Guardrails for input/output validation
- Built-in tracing and observability
- Works with Responses API and Chat Completions API

### 3.3 CrewAI

**URL**: https://github.com/crewAIInc/crewAI (56k+ stars)

- Role-based agent collaboration
- **Crews** (autonomous) + **Flows** (event-driven control)
- Sequential and hierarchical process modes
- Examples: trip planner, stock analysis, job posting, landing page generator
- DeepLearning.AI courses: "Multi AI Agent Systems with CrewAI"

### 3.4 AutoGen (Microsoft)

**URL**: https://github.com/microsoft/autogen

- Conversation-driven multi-agent
- Human-in-the-loop support
- Code execution integration
- Group chat patterns

### 3.5 GPT-Researcher

**URL**: https://github.com/assafelovic/gpt-researcher

- Autonomous research agent with multiple specialized sub-agents
- Writer ↔ Critic loop (evaluator-optimizer pattern)
- Good example of combining planning with parallel research

### 3.6 GPT-Newspaper

**URL**: https://github.com/assafelovic/gpt-newspaper

- 6 specialized sub-agents for newspaper creation
- Built on LangGraph
- Demonstrates hierarchical multi-agent with feedback loops

### 3.7 LangChain Academy

**URL**: https://academy.langchain.com/

Free courses covering multi-agent patterns, LangGraph workflows, and production deployment.

---

## 4. Design Patterns — Catalog with Names and Descriptions

### Pattern 1: Single-Agent ReAct Loop

```
User → [LLM ↔ Tool calls] → Response
```

- LLM reasons, picks a tool, observes result, repeats until done
- Simplest agentic pattern; your Chat Agent uses this
- **Best for**: Focused tasks with clear tool boundaries
- **Anti-pattern when**: Task requires multiple independent expertise areas

### Pattern 2: Plan-Execute-Replan (Orchestrator-Workers)

```
Planner → Executor → Replanner → Executor → ... → Report
```

- Separate planning from execution
- Replanner evaluates results and adjusts
- Your AIOps Agent uses this
- **Best for**: Complex multi-step tasks where steps need auditability
- **Trade-off**: Higher latency; plan may need revision mid-execution

### Pattern 3: Supervisor Routing

```
User → Supervisor → [Specialist A | Specialist B | Specialist C] → Supervisor → Response
```

- Central routing agent classifies input and delegates
- Specialists have independent scratchpads and tools
- Your multi-agent module uses this
- **Best for**: Distinct categories of expertise that benefit from specialized prompts/tools
- **Key design choice**: Rule-based router vs LLM-based router

### Pattern 4: Handoff / Escalation Chain

```
Triage Agent → (handoff) → Specialist A → (handoff) → Specialist B → Response
```

- Agents transfer control to each other based on conversation context
- Used by OpenAI Agents SDK as a first-class concept
- **Best for**: Customer support, service desk scenarios
- **Real product**: ChatGPT plugin routing, OpenAI Agents SDK

### Pattern 5: Hierarchical Teams

```
Supervisor → [Team Lead A → [Worker1, Worker2], Team Lead B → [Worker3, Worker4]]
```

- Nested supervisor pattern; teams of teams
- Each team lead is itself a supervisor
- **Best for**: Large systems with many specialists (>5)
- **Real example**: Your project's potential evolution path

### Pattern 6: Evaluator-Optimizer (Critic Loop)

```
Generator → Evaluator → [Accept | Revise with feedback] → Generator → ...
```

- Two LLMs: one generates, one evaluates against criteria
- Loop continues until quality threshold met
- **Best for**: Translation, content creation, complex analysis
- **Real example**: GPT-Newspaper's writer ↔ critic loop

### Pattern 7: Parallel Voting / Ensemble

```
User → [LLM1, LLM2, LLM3] → Aggregator → Response
```

- Same task sent to multiple agents/models simultaneously
- Results aggregated by voting, averaging, or selection
- **Best for**: High-stakes decisions, reducing hallucination
- **Real example**: Code review by multiple specialist prompts

### Pattern 8: Fallback / Degradation Chain

```
Primary Agent → [fails?] → Fallback Agent → [fails?] → Static Response
```

- Cascading fallback when primary agent/tool fails
- Exponential backoff with retries (you already do this for MCP)
- **Best for**: Production reliability; your MCP retry pattern is a variant
- **Extension**: Route to cheaper/faster model when primary is unavailable

### Pattern 9: Shared State Blackboard

```
Agent A → [writes to blackboard] → Agent B reads → Agent C reads → Response
```

- All agents share a common state structure
- Each agent reads relevant portions, writes results
- Your `MultiAgentState` with `Annotated[List, operator.add]` is this pattern
- **Best for**: Agents that need to build on each other's work

### Pattern 10: Dynamic Task Decomposition

```
User → Decomposer → [Task1, Task2, ...] → Parallel/Squential Workers → Synthesizer
```

- LLM dynamically breaks task into subtasks at runtime
- Unlike parallelization, subtasks aren't pre-defined
- **Best for**: Complex tasks where you can't predict structure
- **Real example**: OpenAI's orchestrator-workers pattern in Agents SDK

---

## 5. Real Product Examples — How Major Products Handle Multi-Agent/Tool Routing

### 5.1 ChatGPT (OpenAI)

**Architecture**: Triage model → Plugin/Tool routing

- User query classified by intent
- Routed to: ChatGPT search, Code Interpreter, DALL-E, or third-party plugins
- **Plugin routing**: LLM selects from available plugins based on query context
- **Model switching**: GPT-4o for complex tasks, GPT-4o-mini for simple ones
- **Handoffs**: Agents SDK enables explicit `handoffs` between triage and specialist agents

**Key design**: Single unified interface; user doesn't choose the routing. The triage agent decides.

### 5.2 Claude (Anthropic)

**Architecture**: Tool Use + MCP (Model Context Protocol)

- Single model with dynamically loaded tools
- **Tool selection**: Model decides which tool(s) to call based on query
- **MCP**: Standardized protocol for tool integration — your project uses this
- **Agentic patterns**: Anthropic recommends starting simple, adding complexity only when needed
- No explicit multi-agent routing — instead, one augmented LLM with rich toolset

**Key design**: Prefer one powerful agent with many tools over multiple specialized agents. But when tools get too numerous (>15-20), consider the Supervisor pattern to group them.

### 5.3 Cursor / GitHub Copilot

**Architecture**: Orchestrator-Workers for multi-file code changes

- Central agent analyzes task → determines which files need changes
- Worker agents handle individual file edits in parallel
- Results synthesized back together
- Uses the Plan-Execute pattern internally

### 5.4 Devin (Cognition)

**Architecture**: Full autonomous agent with sandboxed environment

- Single agent with access to: terminal, code editor, browser
- Plan → Execute → Observe → Replan loop
- Long-running with checkpointing for human review
- Uses the Autonomous Agent pattern from Anthropic's taxonomy

### 5.5 Navan (Travel Agent)

**Architecture**: Routing + RAG

- User query → classify intent (booking, policy, support)
- Routed to specialized agent with domain-specific knowledge
- File search tool for RAG from knowledge-base articles
- Per-user vector stores for personalized responses

---

## 6. Relevance to Your Project (OnCall-Agent)

Your project already implements two of the five Anthropic workflow patterns:

| Your Component | Pattern | Reference |
|---|---|---|
| `app/services/rag_agent_service.py` | **ReAct Loop** | Anthropic's "Augmented LLM" |
| `app/agent/aiops/` (planner, executor, replanner) | **Plan-Execute-Replan** | LangGraph's Orchestrator-Workers |
| `app/agent/multi_agent/supervisor.py` | **Supervisor Routing** | LangGraph's Agent Supervisor |
| `app/agent/multi_agent/base_specialist.py` | Specialist abstraction | OpenAI's Agents SDK handoff targets |

### Potential Next Steps Based on Research

1. **Unified Interface**: Your `/api/chat` and `/api/aiops` are separate endpoints. Consider a single entry point with a router (Anthropic's Routing pattern) that dispatches to chat or aiops agents.

2. **Hierarchical Teams**: If you add more specialists (e.g., security expert, network expert), wrap them in team leads under a meta-supervisor.

3. **Fallback Chains**: Your MCP retry logic (exponential backoff) is already this pattern. Extend it to agent-level fallback: if log_analyzer fails, fall back to knowledge_retriever for cached solutions.

4. **Evaluator-Optimizer**: Add a critic agent that reviews the final report for completeness/accuracy before returning to the user.

5. **Handoff Pattern**: Instead of the supervisor collecting all results, let specialists hand off to each other when they discover cross-domain issues (e.g., log analyzer finds OOM → hand off to monitor expert for memory metrics).

---

## 7. Additional Resources

| Resource | URL | Type |
|----------|-----|------|
| LangGraph Docs (Multi-Agent) | https://langchain-ai.github.io/langgraph/concepts/multi_agent/ | Docs |
| LangChain Academy | https://academy.langchain.com/ | Course |
| OpenAI Agents SDK Docs | https://platform.openai.com/docs/guides/agents | Docs |
| Anthropic Tool Use Docs | https://docs.anthropic.com/en/docs/build-with-claude/tool-use/overview | Docs |
| CrewAI Docs | https://docs.crewai.com | Docs |
| DeepLearning.AI Multi-Agent Course | https://www.deeplearning.ai/short-courses/multi-ai-agent-systems-with-crewai/ | Course |
| Anthropic Cookbook | https://github.com/anthropics/anthropic-cookbook | Code |
| LangGraph Examples | https://github.com/langchain-ai/langgraph/tree/main/examples | Code |
| AutoGen Examples | https://github.com/microsoft/autogen/tree/main/website/docs/tutorial | Code |
| OpenAI CUA Quickstart | https://github.com/openai/openai-cua-quickstart | Code |

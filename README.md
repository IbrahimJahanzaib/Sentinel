# Sentinel

**Autonomous AI reliability research agent.** Sentinel proactively discovers how LLM-based systems fail — before your users do.

Instead of waiting for failures to surface in production, Sentinel runs a continuous research cycle: it generates hypotheses about what could go wrong, designs experiments to test them, executes those experiments against your target system, classifies any failures it finds, proposes fixes, and validates that those fixes actually work. Every finding is stored in a persistent knowledge graph so each cycle builds on the last.

---

## What Sentinel Does

```
┌─────────────────────────────────────────────────────────────────────┐
│                         RESEARCH CYCLE                              │
│                                                                     │
│   ┌────────────┐    ┌────────────┐    ┌────────────┐               │
│   │ Hypothesis │───▶│ Experiment │───▶│  Failure   │               │
│   │   Engine   │    │  Executor  │    │ Discovery  │               │
│   └────────────┘    └────────────┘    └─────┬──────┘               │
│         ▲                                   │                       │
│         │           ┌────────────┐    ┌─────▼──────┐               │
│         │           │ Simulation │◀───│Intervention│               │
│         │           │   Engine   │    │   Engine   │               │
│         │           └─────┬──────┘    └────────────┘               │
│         │                 │                                         │
│         └─────── Learning ◀┘                                        │
│                (Memory Graph)                                       │
└─────────────────────────────────────────────────────────────────────┘
```

Each cycle runs through **six autonomous agents**, coordinated by the **Control Plane** and gated by a **risk-tiered approval system**:

1. **Hypothesis Engine** — reads the target system description and past findings from the memory graph, generates testable hypotheses about what could fail and why
2. **Experiment Architect** — turns each hypothesis into concrete test cases with specific inputs, expected correct behavior, and expected failure behavior
3. **Experiment Executor** — runs each test case N times (with timeout, parallelism, and budget enforcement), capturing outputs, tool calls, retrieved chunks, latency, and errors
4. **Failure Discovery** — two-phase LLM evaluation (per-run judgement then aggregate summary); classifies failures using the taxonomy and assigns severity S0–S4
5. **Intervention Engine** — proposes concrete, actionable fixes: prompt mutations, guardrails, tool policy changes, config changes, and architectural recommendations — ranked by effectiveness vs. effort
6. **Simulation Engine** — applies each fix to the target system, re-runs the same experiments (counterfactual replay), and classifies the outcome: `fixed`, `partially_fixed`, `no_effect`, or `regression`

Every step feeds back into the **Memory Graph** so the next cycle generates novel hypotheses informed by what's already been found.

---

## Approval System

Every action passes through a **risk-tiered approval gate** before execution:

```
Action Request ──▶ Risk Evaluator
                        │
                 ┌──────┼──────┐
                 ▼      ▼      ▼
               SAFE   REVIEW  BLOCK
                │       │       │
                ▼       ▼       ▼
           Auto-OK   Human?   Reject
```

The risk level depends on the operating mode, the action type, and any associated severity:

| Action | LAB | SHADOW | PRODUCTION |
|--------|-----|--------|------------|
| Generate hypotheses | SAFE | SAFE | REVIEW |
| Design experiments | SAFE | SAFE | REVIEW |
| Execute experiment | SAFE | REVIEW | REVIEW |
| Classify failure | SAFE | SAFE (S3+ → REVIEW) | REVIEW |
| Validate intervention | SAFE | REVIEW | REVIEW |
| Destructive test | SAFE | BLOCK | BLOCK |

Every approval decision (approve or reject) is logged to an immutable **audit trail** in the database.

---

## Failure Taxonomy

Sentinel classifies discovered failures into six primary classes:

| Class | Description |
|-------|-------------|
| **REASONING** | Logic errors, hallucination, self-contradiction, goal drift |
| **LONG_CONTEXT** | Context window failures, attention dilution, forgotten instructions |
| **TOOL_USE** | Wrong tool called, invalid parameters, missing calls, tool loops |
| **FEEDBACK_LOOP** | Error cascades where one agent's bad output corrupts the next |
| **DEPLOYMENT** | Timeouts, rate limiting, memory overflow under load |
| **SECURITY** | Prompt injection, credential access, data exfiltration, evasion |

Security failures have eight fine-grained subtypes: `credential_access`, `data_exfiltration`, `unauthorized_action`, `privilege_escalation`, `injection_susceptible`, `evasion_bypass`, `memory_poisoning`, `platform_specific_attack`.

### Severity Levels

| Level | Impact | Action |
|-------|--------|--------|
| S0 | Benign | Monitor |
| S1 | UX degradation | Review |
| S2 | Business risk | Investigate |
| S3 | Serious risk | Mitigate |
| S4 | Critical | Immediate action |

---

## Three Operating Modes

| Mode | Use Case | Approval | Destructive Tests |
|------|----------|----------|-------------------|
| **LAB** | Development and research | Auto-approved | Allowed |
| **SHADOW** | Observe production traffic passively | Human review for S3+ | Read-only |
| **PRODUCTION** | Active production monitoring | Human approval for everything | Blocked |

Mode transitions are strictly enforced: LAB → SHADOW → PRODUCTION only. Skipping modes (LAB → PRODUCTION) is blocked. Stepping back from PRODUCTION → SHADOW is allowed as a regression fallback.

---

## Memory Graph

Every research cycle feeds into a **persistent knowledge graph** so each subsequent cycle builds on what's already been discovered — generating novel hypotheses instead of repeating past work.

```
Cycle 1 ──▶ Nodes + Edges stored in DB
                │
Cycle 2 ──▶ Hypothesis Engine reads graph ──▶ generates only NEW hypotheses
                │
Cycle 3 ──▶ Cross-cycle linking ──▶ deeper analysis of recurring patterns
```

The graph stores five node types (`CYCLE`, `HYPOTHESIS`, `FAILURE`, `INTERVENTION`, `EXPERIMENT`) connected by directed edges (`TESTED_IN`, `CAUSED_BY`, `CONFIRMED_BY`, `PROPOSED_FOR`, `FIXED_BY`, `RELATED_TO`, `INFORMS`).

**Key queries the memory answers:**
- What hypotheses have we already tested? (avoid repetition)
- What failures exist in each failure class? (go deeper)
- Which interventions worked vs. failed? (propose better fixes)
- What did we know at time T? (temporal knowledge)

---

## Multi-Provider LLM Support

Sentinel's research agents can run on any of these providers — pick what works for your cost and privacy requirements:

| Provider | Cost | Notes |
|----------|------|-------|
| **Ollama** | Free (local) | Privacy-first, fully offline, unlimited runs |
| **Groq** | Free tier available | Fast inference, high throughput |
| **OpenRouter** | Many free models | DeepSeek, Qwen, Llama, Mistral and more |
| **Together** | $25 free credits | Quality open models |
| **OpenAI** | Paid | GPT-4o and variants |
| **Anthropic** | Paid | Claude (default) |

All providers share the same `ModelClient` interface with `generate()` and `generate_structured()` methods. Switch by changing one line in your config. Every call is tracked by the **CostTracker** — per-provider token counts, USD cost, and budget enforcement.

---

## Installation

```bash
git clone https://github.com/IbrahimJahanzaib/Sentinel.git
cd Sentinel
pip install -e .
```

Set your API keys:

```bash
cp .env.example .env
# Edit .env and add your keys
```

Initialise the project:

```bash
sentinel init
```

This creates `.sentinel/config.yaml` and initialises the SQLite database with all tables.

---

## Configuration

After running `sentinel init`, edit `.sentinel/config.yaml`:

```yaml
mode: lab  # lab | shadow | production

models:
  default: anthropic  # switch to ollama for free local inference
  providers:
    anthropic:
      api_key: ${ANTHROPIC_API_KEY}
      model: claude-sonnet-4-20250514
    ollama:
      model: llama3
      base_url: http://localhost:11434

research:
  max_hypotheses_per_run: 10
  max_experiments_per_hypothesis: 3
  default_runs_per_experiment: 5

experiments:
  cost_limit_usd: 10.0
  max_parallel: 5
  default_timeout_seconds: 300

risk:
  auto_approve_safe: true
  block_on_destructive: true

approval:
  mode: interactive  # interactive | auto_approve | auto_reject
  timeout_seconds: 300
```

---

## CLI

```bash
# Initialise a new Sentinel project
sentinel init

# Run a research cycle with a focus area
sentinel research --focus "tool use failures in multi-step tasks"
sentinel research --focus "reasoning failures"

# Generate a report (markdown or JSON, file or stdout)
sentinel report --format markdown --output findings.md
sentinel report --format json --output report.json
sentinel report                       # markdown to stdout

# Browse discovered failures (Rich-formatted table)
sentinel failures                     # all failures
sentinel failures --severity S2+      # S2 and above only
sentinel failures --class SECURITY    # filter by failure class

# Browse hypotheses (Rich-formatted table)
sentinel hypotheses                   # all hypotheses
sentinel hypotheses --status confirmed
sentinel hypotheses --status untested

# Launch the interactive TUI
sentinel tui
```

### Report Formats

**Markdown** — human-readable report with four sections:
- Executive Summary (cycle count, failure count, cost)
- Severity Distribution table (S4 → S0)
- Findings by Failure Class (grouped, with evidence)
- Interventions & Recommendations (grouped by validation status)

**JSON** — structured dict for programmatic use:
```json
{
  "summary": { "cycles": 5, "failures": 12, "interventions": 8, "total_cost_usd": 1.23 },
  "severity_distribution": { "S3": { "label": "Serious Risk", "action": "Mitigate", "count": 4 } },
  "findings": [ ... ],
  "interventions": [ ... ]
}
```

---

## Python API

```python
import asyncio
from sentinel import create_sentinel
from sentinel.config.modes import Mode

async def main():
    sentinel = await create_sentinel(
        mode=Mode.LAB,
        db_url="sqlite+aiosqlite:///sentinel.db"
    )

    # Your target system must implement the TargetSystem protocol:
    #   async def run(query, context_setup="") -> TargetResult
    #   async def apply_intervention(type, params) -> None
    #   async def reset_interventions() -> None
    #   def describe() -> str
    target = YourTargetSystem()

    results = await sentinel.research_cycle(
        target=target,
        focus="reasoning failures in multi-step tasks",
        max_hypotheses=5,
    )

    print(f"Hypotheses tested  : {len(results.hypotheses)}")
    print(f"Failures confirmed : {len(results.confirmed_failures)}")
    print(f"Interventions      : {len(results.interventions)}")
    print(f"Validations        : {len(results.validations)}")
    print(f"Total cost         : ${results.cost_summary['total_cost_usd']:.4f}")

    await sentinel.close()

asyncio.run(main())
```

### Generate reports programmatically

```python
from sentinel.db.connection import init_db, close_db
from sentinel.reporting import (
    get_cycles, get_failures, get_interventions,
    generate_markdown_report, generate_json_report,
)

async def make_report():
    await init_db("sqlite+aiosqlite:///sentinel.db")

    cycles = await get_cycles()
    failures = await get_failures(min_severity="S2+")
    interventions = await get_interventions()

    # Markdown for humans
    md = generate_markdown_report(cycles, failures, interventions)
    Path("findings.md").write_text(md)

    # JSON for tooling
    import json
    data = generate_json_report(cycles, failures, interventions)
    Path("report.json").write_text(json.dumps(data, indent=2))

    await close_db()
```

### Monitor an existing pipeline (Shadow mode)

```python
from sentinel.integrations import PipelineAdapter

adapter = PipelineAdapter(name="my-app", shadow_mode=True)

async def monitored_llm_call(prompt, model="gpt-4"):
    ctx = adapter.create_context(model=model, provider="openai", prompt=prompt)
    ctx = await adapter.pre_request(ctx)       # no-op in shadow mode
    response = await your_existing_llm_call(prompt)
    await adapter.post_request(
        ctx, output=response.text,
        input_tokens=response.usage.input, output_tokens=response.usage.output,
        latency_ms=response.latency_ms,
    )
    return response

# Feed captured traffic into a research cycle
target = adapter.as_target_system()
results = await sentinel.research_cycle(target=target, focus="production errors")
```

### Real-time gateway monitoring

```python
from sentinel.integrations.gateway_plugin import GatewayMonitor, ConsoleAlerter, FileAlerter

monitor = GatewayMonitor(
    "ws://your-gateway:8080/events",
    high_latency_threshold_ms=5000,
)
monitor.add_alerter(ConsoleAlerter(min_severity="S2"))
monitor.add_alerter(FileAlerter("alerts.md", min_severity="S3"))

await monitor.start()  # blocking; or use start_background() for a Task
```

---

## Project Structure

```
sentinel/
├── agents/                     # The 6 autonomous research agents
│   ├── base.py                 # TargetSystem protocol + TargetResult
│   ├── hypothesis_engine.py    # Agent 1: generates failure hypotheses
│   ├── experiment_architect.py # Agent 2: designs test cases
│   ├── experiment_executor.py  # Agent 3: runs experiments with budget/timeout
│   ├── failure_discovery.py    # Agent 4: two-phase LLM failure classification
│   ├── intervention_engine.py  # Agent 5: proposes concrete fixes
│   └── simulation_engine.py    # Agent 6: counterfactual replay validation
├── config/
│   ├── modes.py                # LAB / SHADOW / PRODUCTION + transition rules
│   └── settings.py             # YAML config with ${ENV_VAR} expansion
├── core/
│   ├── approval_gate.py        # Risk-tiered human-in-the-loop approval
│   ├── control_plane.py        # Orchestrates the full research cycle
│   ├── cost_tracker.py         # Per-provider token usage and USD cost tracking
│   └── risk_policy.py          # SAFE / REVIEW / BLOCK rules per mode
├── db/
│   ├── connection.py           # Async SQLAlchemy engine + session factory
│   ├── models.py               # ORM: Cycle, Hypothesis, Experiment, Run, Failure, Intervention, AuditEntry
│   └── audit.py                # Immutable audit trail for all actions
├── integrations/
│   ├── model_client.py         # Multi-provider async LLM client (6 providers)
│   ├── pipeline_adapter.py     # Hook wrapper for existing LLM calls + TargetSystem bridge
│   └── gateway_plugin/
│       ├── models.py           # EventType, RequestContext, GatewayEvent, AlertFinding
│       ├── monitor.py          # WebSocket consumer with auto-reconnect and heuristic analysis
│       ├── alerter.py          # Console, File, and Webhook alerters with severity filtering
│       └── adapters/
│           ├── base.py         # GatewayAdapter protocol
│           └── generic.py      # GenericAdapter for standardized event schema
├── memory/
│   ├── models.py               # MemoryNode + MemoryEdge ORM tables, NodeType/EdgeType enums
│   ├── graph.py                # In-memory knowledge graph: query, traverse, summarize for agents
│   └── repository.py           # DB-backed CRUD, populate graph from cycles, cross-cycle linking
├── taxonomy/
│   └── failure_types.py        # FailureClass, SecuritySubtype, Severity enums
├── reporting/
│   ├── queries.py              # Async DB query functions (cycles, failures, hypotheses, interventions)
│   ├── markdown_report.py      # Human-readable markdown reports with severity tables
│   └── json_report.py          # Structured JSON for programmatic use
├── tui/                        # Terminal UI (Textual)
│   └── app.py
├── cli.py                      # Click CLI entry point
└── __init__.py                 # create_sentinel() factory + Sentinel class
```

---

## Tech Stack

- **Python 3.11+** with async/await throughout
- **SQLAlchemy 2.0** (async) + **aiosqlite** / **asyncpg** + **Alembic** migrations
- **Pydantic v2** — structured, validated data models for every agent input/output
- **Anthropic / OpenAI / httpx** — multi-provider LLM support (6 providers)
- **Click** — CLI
- **Textual** — terminal UI
- **Rich** — terminal output formatting

---

## Build Status

| Phase | Status | Description |
|-------|--------|-------------|
| 1 — Skeleton & Config | Done | Project structure, config system, DB models, taxonomy, `sentinel init` CLI |
| 2 — LLM Client | Done | Multi-provider async client (6 providers), cost tracker, 14 passing tests |
| 3 — Research Agents | Done | All 6 agents: hypothesis, experiment architect, executor, failure discovery, intervention, simulation |
| 4 — Control Plane | Done | Full cycle orchestration, risk policy (SAFE/REVIEW/BLOCK), approval gate, audit trail |
| 5 — Memory Graph | Done | Persistent cross-cycle knowledge graph with graph queries and agent integration, 33 passing tests |
| 6 — Integrations | Done | Pipeline adapter with TargetSystem bridge, WebSocket gateway monitor, 3 alerters, 36 passing tests |
| 7 — Reporting | Done | Markdown and JSON report generation, DB query helpers, CLI `report`/`failures`/`hypotheses` commands, 18 passing tests |
| 8 — CLI & TUI | Pending | Full CLI commands, interactive terminal UI |
| 9 — Tests & Docs | Pending | Full test suite, examples |

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.

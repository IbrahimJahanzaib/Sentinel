# Sentinel — Complete Testing Guide (Phases 1-9)

Feed this into Claude Code. Run each phase's tests in order. If a phase fails, fix it before moving on.

---

## Phase 1: Project Skeleton & Config

### Test 1.1 — Init creates config
```bash
# Remove any existing config
rm -rf .sentinel/

# Run init
sentinel init

# Verify
ls -la .sentinel/config.yaml
cat .sentinel/config.yaml
```
**Pass if:** `.sentinel/config.yaml` exists with valid YAML containing mode, database, models, research, experiments, risk, and approval sections.

### Test 1.2 — Config loads environment variables
```bash
# Set a test key
export ANTHROPIC_API_KEY="test-key-123"

# Verify config resolves it
python -c "
from sentinel.config.settings import load_config
config = load_config()
print(config.models.providers['anthropic'].api_key)
"
```
**Pass if:** Prints `test-key-123`, not `${ANTHROPIC_API_KEY}`.

### Test 1.3 — Database tables created
```bash
python -c "
import asyncio
from sentinel.db.connection import get_engine
from sentinel.db.models import Base

async def test():
    engine = await get_engine('sqlite:///test_sentinel.db')
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # List tables
    import sqlite3
    db = sqlite3.connect('test_sentinel.db')
    tables = db.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
    for t in tables:
        print(t[0])
    db.close()

asyncio.run(test())
rm test_sentinel.db
"
```
**Pass if:** Prints table names including: hypotheses, experiments, experiment_runs, failures, interventions, cycles (names may vary based on your models).

---

## Phase 2: Modes

### Test 2.1 — Mode enum works
```bash
python -c "
from sentinel.config.modes import Mode

print(Mode.LAB)
print(Mode.SHADOW)
print(Mode.PRODUCTION)
"
```
**Pass if:** Prints all three modes without error.

### Test 2.2 — Mode transitions enforce rules
```bash
python -c "
from sentinel.config.modes import Mode

# These should work
assert Mode.can_transition(Mode.LAB, Mode.SHADOW), 'LAB -> SHADOW should be allowed'
assert Mode.can_transition(Mode.SHADOW, Mode.PRODUCTION), 'SHADOW -> PRODUCTION should be allowed'
assert Mode.can_transition(Mode.PRODUCTION, Mode.SHADOW), 'PRODUCTION -> SHADOW should be allowed'

# This should fail
assert not Mode.can_transition(Mode.LAB, Mode.PRODUCTION), 'LAB -> PRODUCTION should be BLOCKED'

print('All mode transition tests passed')
"
```
**Pass if:** Prints "All mode transition tests passed". If `can_transition` doesn't exist, the mode logic needs fixing.

---

## Phase 3: Taxonomy

### Test 3.1 — Failure classes defined
```bash
python -c "
from sentinel.taxonomy.failure_types import FailureClass, Severity

# All 6 classes exist
for fc in [FailureClass.REASONING, FailureClass.LONG_CONTEXT, FailureClass.TOOL_USE, 
           FailureClass.FEEDBACK_LOOP, FailureClass.DEPLOYMENT, FailureClass.SECURITY]:
    print(f'{fc.name}: {fc.value}')

print()

# All severity levels exist
for s in [Severity.S0, Severity.S1, Severity.S2, Severity.S3, Severity.S4]:
    print(f'{s.name}: {s.value}')
"
```
**Pass if:** Prints all 6 failure classes and all 5 severity levels.

### Test 3.2 — Security subtypes defined
```bash
python -c "
from sentinel.taxonomy.failure_types import SecuritySubtype

subtypes = ['credential_access', 'data_exfiltration', 'unauthorized_action', 
            'privilege_escalation', 'injection_susceptible', 'evasion_bypass',
            'memory_poisoning', 'platform_specific_attack']

for st in subtypes:
    print(f'{st}: {SecuritySubtype(st)}')
print('All security subtypes exist')
"
```
**Pass if:** All 8 subtypes print without error.

---

## Phase 4: LLM Client

### Test 4.1 — Can call Anthropic
```bash
python -c "
import asyncio
from sentinel.integrations.model_client import ModelClient

async def test():
    client = ModelClient(provider='anthropic')
    response = await client.generate(
        messages=[{'role': 'user', 'content': 'Say hello in exactly 3 words.'}],
        max_tokens=50
    )
    print(f'Response: {response}')

asyncio.run(test())
"
```
**Pass if:** Returns a response from Claude. If you don't have an API key set, this will fail — that's expected, just make sure the error is about authentication, not a code bug.

### Test 4.2 — Structured output works
```bash
python -c "
import asyncio
from sentinel.integrations.model_client import ModelClient

async def test():
    client = ModelClient(provider='anthropic')
    result = await client.generate_structured(
        messages=[{'role': 'user', 'content': 'Give me a JSON object with fields: name (string), age (integer)'}],
        system='Respond ONLY with valid JSON. No other text.'
    )
    print(f'Result: {result}')
    assert isinstance(result, dict), 'Should return a dict'
    print('Structured output works')

asyncio.run(test())
"
```
**Pass if:** Returns a parsed dict like `{"name": "...", "age": ...}`.

### Test 4.3 — Cost tracking records usage
```bash
python -c "
import asyncio
from sentinel.integrations.model_client import ModelClient
from sentinel.core.cost_tracker import CostTracker

async def test():
    tracker = CostTracker()
    client = ModelClient(provider='anthropic', cost_tracker=tracker)
    
    await client.generate(
        messages=[{'role': 'user', 'content': 'Say hi'}],
        max_tokens=10
    )
    
    print(f'Total tokens: {tracker.total_tokens}')
    print(f'Total cost: \${tracker.total_cost_usd:.4f}')
    assert tracker.total_tokens > 0, 'Should have recorded tokens'

asyncio.run(test())
"
```
**Pass if:** Prints non-zero token count and cost. Adjust method/property names to match your implementation.

---

## Phase 5: Hypothesis Engine

### Test 5.1 — Generates hypotheses from a system description
```bash
python -c "
import asyncio
from sentinel.agents.hypothesis_engine import HypothesisEngine

async def test():
    engine = HypothesisEngine()
    
    system_description = '''Simple RAG pipeline that answers questions about Python documentation.
    Uses 500-token fixed chunking, top-3 retrieval with no relevance threshold, 
    and a basic system prompt with no anti-hallucination instructions.'''
    
    hypotheses = await engine.generate(
        system_description=system_description,
        focus='reasoning',
        max_hypotheses=3,
        previous_findings=[]
    )
    
    print(f'Generated {len(hypotheses)} hypotheses:')
    for h in hypotheses:
        print(f'  [{h.failure_class}] {h.description}')
        print(f'  Expected severity: {h.expected_severity}')
        print()

asyncio.run(test())
"
```
**Pass if:** Prints 3 plausible hypotheses about reasoning failures in a RAG system. Each should have a failure_class and severity.

### Test 5.2 — Hypotheses are stored in DB
```bash
python -c "
import asyncio
import sqlite3

# After running test 5.1, check the database
db = sqlite3.connect('sentinel.db')
rows = db.execute('SELECT * FROM hypotheses').fetchall()
print(f'Hypotheses in DB: {len(rows)}')
for row in rows:
    print(f'  {row}')
db.close()
"
```
**Pass if:** Shows the hypotheses from test 5.1 stored in the database. Adjust table name if different.

---

## Phase 6: Experiment Architect

### Test 6.1 — Designs experiments for a hypothesis
```bash
python -c "
import asyncio
from sentinel.agents.experiment_architect import ExperimentArchitect

async def test():
    architect = ExperimentArchitect()
    
    # Mock hypothesis
    class MockHypothesis:
        id = 'hyp_test_001'
        description = 'The RAG system will hallucinate specific details when retrieved context is partially relevant but does not contain the exact answer.'
        failure_class = 'REASONING'
        expected_severity = 'S2'
    
    experiments = await architect.design(
        hypothesis=MockHypothesis(),
        max_experiments=3
    )
    
    print(f'Designed {len(experiments)} experiments:')
    for e in experiments:
        print(f'  Input: {e.input}')
        print(f'  Expected correct: {e.expected_correct_behavior}')
        print(f'  Expected failure: {e.expected_failure_behavior}')
        print(f'  Runs: {e.num_runs}')
        print()

asyncio.run(test())
"
```
**Pass if:** Prints 3 concrete experiments with realistic inputs and clear expected behaviors. The inputs should be questions designed to trigger partial-match hallucination.

---

## Phase 7: Experiment Executor + Failure Discovery

These need a real target to run against. Build the targets first (see targets spec), then:

### Test 7.1 — Executor runs experiments against RAG target
```bash
python -c "
import asyncio
from sentinel.agents.experiment_executor import ExperimentExecutor
from targets.simple_rag.target import SimpleRAGTarget

async def test():
    target = SimpleRAGTarget()
    await target.setup()
    
    executor = ExperimentExecutor()
    
    # Mock experiment
    class MockExperiment:
        id = 'exp_test_001'
        hypothesis_id = 'hyp_test_001'
        input = 'How do I set up a Kubernetes cluster?'  # NOT in the docs
        expected_correct_behavior = 'States that information about Kubernetes is not available'
        expected_failure_behavior = 'Provides Kubernetes setup instructions fabricated from partial context'
        num_runs = 3
    
    runs = await executor.run(MockExperiment(), target=target)
    
    print(f'Completed {len(runs)} runs:')
    for r in runs:
        print(f'  Run {r.run_number}:')
        print(f'    Output: {r.output[:150]}...')
        print(f'    Chunks: {len(r.retrieved_chunks)}')
        print(f'    Latency: {r.latency_ms:.0f}ms')
        print(f'    Error: {r.error}')
        print()
    
    await target.teardown()

asyncio.run(test())
"
```
**Pass if:** 3 runs complete. Each has output text, retrieved chunks, latency, no errors. The RAG system probably answered the Kubernetes question using unrelated context — that's the expected failure.

### Test 7.2 — Failure classifier classifies results
```bash
python -c "
import asyncio
from sentinel.agents.failure_discovery import FailureDiscovery

async def test():
    classifier = FailureDiscovery()
    
    # Mock experiment runs (simulate what executor would return)
    class MockRun:
        def __init__(self, output, chunks):
            self.output = output
            self.retrieved_chunks = chunks
            self.error = None
    
    runs = [
        MockRun(
            'To set up a Kubernetes cluster, first install kubectl and configure your nodes...',
            ['Python asyncio provides an event loop...', 'Docker containers can be orchestrated...']
        ),
        MockRun(
            'Kubernetes clusters require a master node and worker nodes. Start by...',
            ['Docker Compose allows multi-container...', 'FastAPI can be deployed with...']
        ),
        MockRun(
            'I don\\'t have specific information about Kubernetes setup in the provided context.',
            ['Python virtual environments isolate...', 'Docker basics include images and containers...']
        ),
    ]
    
    class MockExperiment:
        id = 'exp_test_001'
        hypothesis_id = 'hyp_test_001'
        input = 'How do I set up a Kubernetes cluster?'
        expected_correct_behavior = 'States that information about Kubernetes is not available'
        expected_failure_behavior = 'Provides Kubernetes setup instructions fabricated from partial context'
    
    failure = await classifier.classify(MockExperiment(), runs)
    
    if failure:
        print(f'Failure found:')
        print(f'  Class: {failure.failure_class}')
        print(f'  Subtype: {failure.failure_subtype}')
        print(f'  Severity: {failure.severity}')
        print(f'  Failure rate: {failure.failure_rate}')
        print(f'  Evidence: {failure.evidence[:200]}')
    else:
        print('No failure found (might be a problem — 2/3 runs clearly failed)')

asyncio.run(test())
"
```
**Pass if:** Classifies as REASONING/hallucination, severity S1-S2, failure rate ~0.67 (2 out of 3 failed). If it says "no failure found," the classifier logic needs work.

### Test 7.3 — Executor runs against agent target
```bash
python -c "
import asyncio
from sentinel.agents.experiment_executor import ExperimentExecutor
from targets.simple_agent.target import SimpleAgentTarget

async def test():
    target = SimpleAgentTarget()
    await target.setup()
    
    executor = ExperimentExecutor()
    
    class MockExperiment:
        id = 'exp_test_002'
        hypothesis_id = 'hyp_test_002'
        input = 'What is the weather in Berlin?'  # NOT in mock data
        expected_correct_behavior = 'Reports that weather data for Berlin is not available'
        expected_failure_behavior = 'Fabricates weather data for Berlin or crashes'
        num_runs = 3
    
    runs = await executor.run(MockExperiment(), target=target)
    
    print(f'Completed {len(runs)} runs:')
    for r in runs:
        print(f'  Run {r.run_number}:')
        print(f'    Output: {r.output[:150]}...')
        print(f'    Tool calls: {[(tc.tool_name, tc.arguments) for tc in r.tool_calls]}')
        print(f'    Latency: {r.latency_ms:.0f}ms')
        print()
    
    await target.teardown()

asyncio.run(test())
"
```
**Pass if:** 3 runs complete. Agent called `get_weather` with `Berlin`, got an error response, and either handled it gracefully or didn't. Both outcomes are valid — Sentinel will classify accordingly.

---

## Phase 8: Intervention Engine + Simulation Engine

### Test 8.1 — Intervention engine proposes fixes
```bash
python -c "
import asyncio
from sentinel.agents.intervention_engine import InterventionEngine

async def test():
    engine = InterventionEngine()
    
    class MockFailure:
        id = 'fail_test_001'
        experiment_id = 'exp_test_001'
        hypothesis_id = 'hyp_test_001'
        failure_class = 'REASONING'
        failure_subtype = 'hallucination'
        severity = 'S2'
        failure_rate = 0.67
        evidence = 'The system fabricated Kubernetes setup instructions when asked about Kubernetes, despite no Kubernetes content in the document corpus. Retrieved chunks were about Docker and asyncio.'
    
    interventions = await engine.propose(MockFailure())
    
    print(f'Proposed {len(interventions)} interventions:')
    for i in interventions:
        print(f'  Type: {i.type}')
        print(f'  Description: {i.description[:200]}')
        print(f'  Estimated effectiveness: {i.estimated_effectiveness}')
        print()

asyncio.run(test())
"
```
**Pass if:** Proposes at least 1-2 interventions. Expect things like: prompt_mutation (add anti-hallucination instruction), retrieval_config (add similarity threshold). Each should have a type, description, and effectiveness estimate.

### Test 8.2 — Simulation engine validates a fix
```bash
python -c "
import asyncio
from sentinel.agents.simulation_engine import SimulationEngine
from targets.simple_rag.target import SimpleRAGTarget

async def test():
    target = SimpleRAGTarget()
    await target.setup()
    
    engine = SimulationEngine()
    
    class MockIntervention:
        id = 'int_test_001'
        failure_id = 'fail_test_001'
        type = 'prompt_mutation'
        config = {
            'new_prompt': '''You are a helpful assistant that answers questions about Python and FastAPI.
Use the provided context to answer the user's question.
IMPORTANT: If the retrieved context does not specifically and directly answer the question asked, 
explicitly state that you do not have that information. Do NOT fabricate, infer, or extrapolate 
answers from partially related context.'''
        }
    
    class MockExperiment:
        id = 'exp_test_001'
        input = 'How do I set up a Kubernetes cluster?'
        expected_correct_behavior = 'States that information about Kubernetes is not available'
        expected_failure_behavior = 'Provides Kubernetes setup instructions fabricated from partial context'
        num_runs = 3
    
    result = await engine.validate(MockIntervention(), MockExperiment(), target=target)
    
    print(f'Validation result:')
    print(f'  Status: {result.status}')  # fixed / partially_fixed / no_effect / regression
    print(f'  Before failure rate: {result.before_failure_rate}')
    print(f'  After failure rate: {result.after_failure_rate}')
    print(f'  Summary: {result.summary}')
    
    # Verify target was reset
    await target.reset()
    await target.teardown()

asyncio.run(test())
"
```
**Pass if:** Shows before/after failure rates. The anti-hallucination prompt should reduce the failure rate. Status should be "fixed" or "partially_fixed". Target should reset to original state after.

---

## Phase 9: Control Plane + Approval Gates (Full Cycle)

### Test 9.1 — Full research cycle end-to-end against RAG target
```bash
sentinel research --target simple_rag --focus "reasoning" --max-hypotheses 2
```
**Pass if:** Completes without crashing. Prints hypotheses generated, experiments run, failures found, interventions proposed, validations completed.

**Check the database:**
```bash
python -c "
import sqlite3
db = sqlite3.connect('sentinel.db')
for table in ['hypotheses', 'experiments', 'experiment_runs', 'failures', 'interventions', 'cycles']:
    try:
        count = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        print(f'{table}: {count} rows')
    except:
        print(f'{table}: TABLE NOT FOUND')
db.close()
"
```
**Pass if:** Every table has rows.

### Test 9.2 — Full cycle against agent target
```bash
sentinel research --target simple_agent --focus "tool_use" --max-hypotheses 2
```
**Pass if:** Completes. Finds tool use failures (wrong tool, bad params, unnecessary tool use, poor error handling).

### Test 9.3 — Report generation
```bash
sentinel report --format markdown --output test_report.md
cat test_report.md
```
**Pass if:** Markdown report contains: summary section with counts, findings organized by failure class, severity ratings, evidence, proposed interventions and their validation results.

### Test 9.4 — Memory persists across cycles
```bash
# Run cycle 1
sentinel research --target simple_rag --focus "reasoning" --max-hypotheses 3

# Note the hypotheses generated (copy them down)

# Run cycle 2
sentinel research --target simple_rag --focus "reasoning" --max-hypotheses 3

# Compare: are cycle 2 hypotheses DIFFERENT from cycle 1?
sentinel hypotheses --cycle 1
sentinel hypotheses --cycle 2
```
**Pass if:** Cycle 2 generates different or more specific hypotheses than cycle 1. If they're identical, the memory/learning loop isn't working.

### Test 9.5 — Approval gates in SHADOW mode
```bash
# Change mode to SHADOW
# Edit .sentinel/config.yaml: mode: shadow

sentinel research --target simple_rag --focus "reasoning" --max-hypotheses 2

# Should prompt for human approval on S3+ findings
# Should block destructive tests
```
**Pass if:** Sentinel pauses and asks for approval before proceeding with high-severity actions. Low-severity actions proceed automatically.

### Test 9.6 — Mode transition enforcement
```bash
python -c "
from sentinel.config.modes import Mode

# Try illegal transition
try:
    # This should raise an error or return False
    Mode.transition(Mode.LAB, Mode.PRODUCTION)
    print('FAIL: LAB -> PRODUCTION should be blocked')
except Exception as e:
    print(f'PASS: LAB -> PRODUCTION blocked with: {e}')
"
```
**Pass if:** Blocks the direct LAB → PRODUCTION transition.

### Test 9.7 — Cost tracking after a full cycle
```bash
sentinel research --target simple_rag --focus "reasoning" --max-hypotheses 2
# After it completes, check:
sentinel costs
# Or check programmatically:
python -c "
import sqlite3
db = sqlite3.connect('sentinel.db')
cycles = db.execute('SELECT * FROM cycles ORDER BY id DESC LIMIT 1').fetchone()
print(f'Last cycle: {cycles}')
db.close()
"
```
**Pass if:** Shows total tokens used and estimated cost for the cycle.

### Test 9.8 — Error handling: target that always fails
```bash
python -c "
import asyncio
from targets.base import BaseTarget, TargetResponse

class BrokenTarget(BaseTarget):
    async def setup(self): pass
    async def invoke(self, input):
        raise ConnectionError('Target is down')
    def describe(self):
        return 'A broken target that always crashes'
    async def teardown(self): pass

# Point Sentinel at it
from sentinel.core.control_plane import ControlPlane

async def test():
    cp = ControlPlane()
    target = BrokenTarget()
    try:
        results = await cp.research_cycle(target=target, focus='reasoning', max_hypotheses=1)
        print(f'Handled gracefully: {results}')
    except Exception as e:
        print(f'Crashed with: {e}')
        print('FAIL: Should handle target errors gracefully, not crash')

asyncio.run(test())
"
```
**Pass if:** Sentinel handles the error gracefully — logs it, records it, moves on. Does NOT crash with an unhandled exception.

### Test 9.9 — Error handling: target that times out
```bash
python -c "
import asyncio
from targets.base import BaseTarget, TargetResponse

class SlowTarget(BaseTarget):
    async def setup(self): pass
    async def invoke(self, input):
        await asyncio.sleep(999)  # Never returns
        return TargetResponse(output='', latency_ms=0)
    def describe(self):
        return 'A target that never responds'
    async def teardown(self): pass

from sentinel.core.control_plane import ControlPlane

async def test():
    cp = ControlPlane()
    target = SlowTarget()
    try:
        results = await cp.research_cycle(target=target, focus='reasoning', max_hypotheses=1)
        print(f'Handled gracefully: {results}')
    except asyncio.TimeoutError:
        print('Got timeout — check if config timeout_seconds is respected')
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(test())
"
```
**Pass if:** Times out according to the configured `default_timeout_seconds`, doesn't hang forever.

### Test 9.10 — The manual sanity check

Open `sentinel.db` in a SQLite browser or run:
```bash
python -c "
import sqlite3
db = sqlite3.connect('sentinel.db')

print('=== FAILURES ===')
failures = db.execute('SELECT * FROM failures').fetchall()
for f in failures:
    print(f)
    print()

print('=== INTERVENTIONS ===')
interventions = db.execute('SELECT * FROM interventions').fetchall()
for i in interventions:
    print(i)
    print()

db.close()
"
```

**Read each failure manually. Ask yourself:**
- Does this failure make sense for the target system?
- Is the evidence real or is Sentinel making things up?
- Is the severity reasonable?
- Could you actually implement the proposed intervention?

**This is the most important test.** If the failures are garbage, everything else is cosmetic.

---

## Summary Checklist

| Phase | Test | Status |
|-------|------|--------|
| 1 | Config init | ☐ |
| 1 | Env var resolution | ☐ |
| 1 | DB tables created | ☐ |
| 2 | Mode enum | ☐ |
| 2 | Mode transitions | ☐ |
| 3 | Failure classes | ☐ |
| 3 | Security subtypes | ☐ |
| 4 | LLM client call | ☐ |
| 4 | Structured output | ☐ |
| 4 | Cost tracking | ☐ |
| 5 | Hypothesis generation | ☐ |
| 5 | DB persistence | ☐ |
| 6 | Experiment design | ☐ |
| 7 | Executor vs RAG | ☐ |
| 7 | Failure classifier | ☐ |
| 7 | Executor vs Agent | ☐ |
| 8 | Intervention proposals | ☐ |
| 8 | Simulation validation | ☐ |
| 9 | Full cycle RAG | ☐ |
| 9 | Full cycle Agent | ☐ |
| 9 | Report generation | ☐ |
| 9 | Memory across cycles | ☐ |
| 9 | Approval gates | ☐ |
| 9 | Mode enforcement | ☐ |
| 9 | Cost tracking | ☐ |
| 9 | Broken target handling | ☐ |
| 9 | Timeout handling | ☐ |
| 9 | Manual sanity check | ☐ |

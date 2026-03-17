# SLM Agent Complete Execution Flow

## Overview
This document explains the complete execution flow of the SLM (Small Language Model) Agent system, from Docker container creation to final code generation and testing.

---

## Table of Contents
1. [Pre-Execution Setup](#1-pre-execution-setup)
2. [Docker Container Initialization](#2-docker-container-initialization)
3. [Agent Entry Point](#3-agent-entry-point)
4. [Main Agent Execution](#4-main-agent-execution)
5. [Refinement Loop](#5-refinement-loop)
6. [Testing & Validation](#6-testing--validation)
7. [Port Analysis](#7-port-analysis)
8. [Completion](#8-completion)

---

## 1. Pre-Execution Setup

### 1.1 Docker Image Build (`Dockerfile`)
```
Base Image: ghcr.io/hdl/sim/osvb (includes Verilator, Icarus Verilog)
├── Install Python dependencies (requests, python-dotenv)
├── Create directory structure (/app, /code)
├── Copy agent modules:
│   ├── config/       → Configuration management
│   ├── core/         → Main agent logic, refinement loop
│   ├── hdl/          → HDL code management, port analysis
│   ├── llm/          → LLM API client, response parsing
│   ├── prompts/      → Prompt templates and builders
│   ├── testing/      → Test runners (CocoTB, lint)
│   └── utils/        → Logging utilities
├── Copy main.py (entry point)
└── Set environment variables:
    ├── SLM_API_URL=http://host.docker.internal:8001
    ├── SLM_MODEL=granite
    ├── SLM_MAX_LENGTH=8192
    └── PYTHONPATH=/app
```

### 1.2 Framework Creates Test Environment
The benchmark framework creates:
```
harness/1/
├── docker-compose-agent.yml   → Container configuration
├── run_docker_agent.sh        → Container execution script
├── docs/                      → Documentation files
├── rtl/                       → RTL code directory (target for generation)
├── verif/                     → Verification files (testbenches)
├── rundir/                    → Runtime directory (logs)
├── prompt.json                → Task description
└── src/.env                   → Environment variables (TOPLEVEL, etc.)
```

---

## 2. Docker Container Initialization

### 2.1 Script Execution: `run_docker_agent.sh`
```bash
1. Parse arguments (-d for debug mode)
2. Create/verify Docker bridge network: cvdp-bridge-test-agentic_transformed-6461b92b
3. Get user/group IDs (for file permissions)
4. Execute docker-compose with:
   - Volumes mounted:
     • ./docs → /code/docs
     • ./rtl → /code/rtl
     • ./verif → /code/verif
     • ./rundir → /code/rundir
     • ./prompt.json → /code/prompt.json
   - Working directory: /code
   - User: current user (non-root)
   - Network: shared bridge
5. Container starts, executes ENTRYPOINT: python3 /app/main.py
```

---

## 3. Agent Entry Point

### 3.1 `main.py` Execution
```python
Location: /app/main.py (inside container)

1. Import core agent: from core.agent import IterativeRefinementAgent
2. Create configuration:
   - AgentConfig reads from environment variables:
     • SLM_API_URL → LLM service endpoint
     • SLM_MODEL → Model name (e.g., granite)
     • SLM_MAX_LENGTH → Max tokens (8192)
     • SLM_TIMEOUT → API timeout
   - Set parameters:
     • max_iterations = 3
     • enable_port_validation = True
     • use_few_shot_examples = True
   

3. Initialize agent: agent = IterativeRefinementAgent(config)
4. Run agent: exit_code = agent.run()
5. Exit with code 0 (always, for benchmark compatibility)
```

---

## 4. Main Agent Execution

### 4.1 Agent Initialization (`core/agent.py`)
```python
class IterativeRefinementAgent:
    def __init__(config):
        1. Setup logging → /code/rundir/agent_detailed.log
        2. Initialize components:
           a) LLM Interface:
              • SLMAPIClient → API communication with host LLM
              • ResponseParser → Extract Verilog from LLM responses
           
           b) Prompt Engineering:
              • PromptBuilder → Create optimized prompts with:
                - Few-shot examples
                - Context files
                - Error feedback
                - Token budgeting
           
           c) HDL Operations:
              • CodeManager → File I/O, context gathering
              • PortAnalyzer → Validate port usage
           
           d) Testing:
              • TestRunner → Orchestrate lint + CocoTB tests
           
           e) Refinement:
              • RefinementLoop → Iterative code improvement
```

### 4.2 Main Execution Flow (`agent.run()`)
```python
def run():
    Step 1: Read Task
    ├── Read /code/prompt.json
    └── Extract task description
    
    Step 2: Gather Context
    ├── Scan directories: docs/, rtl/, verif/, rundir/
    ├── Read all existing files
    ├── Store as: {relative_path: content}
    └── Log: "Gathered context from N files"
    
    Step 3: Find Target File
    ├── Check for empty files in /code/rtl/
    ├── OR read TOPLEVEL env var via CodeManager (e.g., "adder" → "adder.sv")
    ├── Create if doesn't exist
    └── Log target file path
    
    Note: TOPLEVEL is read by CodeManager.get_expected_filename()
          NOT by main.py or AgentConfig
    
    Step 4: Run Refinement Loop
    └── Execute iterative code generation (see below)
    
    Step 5: Return Status
    └── Always return 0 (benchmark compatibility)
```

---

## 5. Refinement Loop

### 5.1 Iteration Structure (`core/refinement_loop.py`)
```python
class RefinementLoop:
    def run(task, context, target_file):
        for iteration in 1 to max_iterations (3):
            
            ┌─────────────────────────────────────┐
            │  ITERATION N (1, 2, or 3)          │
            └─────────────────────────────────────┘
            
            ╔════════════════════════════════════════════╗
            ║  PHASE 1: PROMPT CONSTRUCTION              ║
            ╚════════════════════════════════════════════╝
            
            if iteration == 1:
                → Build Initial Prompt:
                  ├── System instruction (Verilog expert)
                  ├── Task description
                  ├── Context files (docs, testbenches, etc.)
                  └── Few-shot examples (if enabled)
            else:
                → Build Refinement Prompt:
                  ├── System instruction
                  ├── Original task
                  ├── Previous code attempt
                  ├── Error messages (categorized)
                  ├── Error category (syntax, undeclared, width, etc.)
                  ├── Iteration number
                  └── Test context (if functional errors)
            
            Print: "PROMPT SENT TO SLM"
            
            ╔════════════════════════════════════════════╗
            ║  PHASE 2: CODE GENERATION                  ║
            ╚════════════════════════════════════════════╝
            
            1. Call LLM API:
               ├── POST to http://host.docker.internal:8001/generate
               ├── Payload: {prompt, max_length, model, temperature}
               ├── Timeout: 300s (configurable)
               └── Resolve host.docker.internal → actual host IP (Linux)
            
            2. Receive Response:
               └── Extract generated_text field
            
            Print: "RESPONSE FROM SLM"
            
            ╔════════════════════════════════════════════╗
            ║  PHASE 3: CODE EXTRACTION & VALIDATION     ║
            ╚════════════════════════════════════════════╝
            
            1. Extract Verilog Code:
               ├── Look for code blocks: ```verilog, ```systemverilog
               ├── OR search for module...endmodule
               └── Clean up formatting
            
            2. Basic Validation:
               ├── Check for "module" keyword
               ├── Check for "endmodule" keyword
               ├── Verify balanced parentheses
               └── If invalid → continue to next iteration
            
            Print: "EXTRACTED CODE"
            
            3. Write Code:
               └── Write to /code/rtl/<target_file>.sv
            
            ╔════════════════════════════════════════════╗
            ║  PHASE 4: TESTING (see section 6)         ║
            ╚════════════════════════════════════════════╝
            
            test_success, errors = test_runner.run()
            
            ╔════════════════════════════════════════════╗
            ║  PHASE 5: SUCCESS PATH                     ║
            ╚════════════════════════════════════════════╝
            
            if test_success:
                if enable_port_validation:
                    → Go to PORT ANALYSIS (see section 7)
                else:
                    → SUCCESS! Return (True, code)
            
            ╔════════════════════════════════════════════╗
            ║  PHASE 6: FAILURE PATH                     ║
            ╚════════════════════════════════════════════╝
            
            else:
                1. Categorize errors:
                   ├── syntax → parse errors
                   ├── undeclared → missing variables
                   ├── type → type mismatches
                   ├── width → bit width issues
                   ├── latch → latch inference
                   ├── timing → timing violations
                   └── general → other errors
                
                2. Log errors (first 500 chars)
                3. Sleep 2 seconds
                4. Continue to next iteration
            
            ═══════════════════════════════════════════
        
        # Max iterations reached
        → Return (False, last_code)
```

---

## 6. Testing & Validation

### 6.1 Test Runner Orchestration (`testing/test_runner.py`)
```python
class TestRunner:
    def run():
        
        ┌────────────────────────────────────┐
        │  STEP 1: COMPILATION CHECK (Lint)  │
        └────────────────────────────────────┘
        
        1. Find RTL files in /code/rtl/
        2. Run lint checks:
           
           Option A: Verilator (preferred)
           ├── Command: verilator --lint-only *.sv
           ├── Check for compilation errors (not warnings)
           ├── Parse output:
           │   • %Error: (without %Error-XXX) → Real error
           │   • %Error-WIDTH, %Error-ASSIGNIN → Warning only
           └── Return: (success=True, "") if compiles
           
           Option B: Icarus Verilog (fallback)
           ├── Command: iverilog -t null -o /dev/null *.sv
           ├── Check return code
           └── Return errors if any
        
        if compilation FAILED:
            → Return (False, errors)
            → Skip testbench execution
        
        ┌────────────────────────────────────┐
        │  STEP 2: TESTBENCH EXECUTION       │
        └────────────────────────────────────┘
        
        1. Search for test files:
           ├── /code/verif/test_*.py
           ├── /code/src/test_*.py
           ├── /code/verif/*_tb.py
           └── /code/src/*_tb.py
        
        2. If test file found:
           a) Setup CocoTB environment:
              ├── VERILOG_SOURCES = /code/rtl/*.sv
              ├── TOPLEVEL = module_name (from filename)
              ├── MODULE = test_module_name
              ├── TOPLEVEL_LANG = verilog
              └── SIM = icarus
           
           b) Run tests:
              ├── Command: cocotb-config --python ...
              ├── Or: python test_runner.py
              ├── Timeout: 120s
              └── Capture stdout/stderr
           
           c) Parse results:
              ├── Look for "PASSED" or "FAILED"
              ├── Check return code
              └── Return (success, errors)
        
        3. If NO test file:
           → Return (None, "")
           → Compilation success is sufficient
        
        ┌────────────────────────────────────┐
        │  FINAL RESULT                      │
        └────────────────────────────────────┘
        
        • (True, "") → Code compiles and tests pass
        • (False, errors) → Compilation or test failure
        • (None, "") → No tests available (compilation OK)
```

---

## 7. Port Analysis

### 7.1 Port Usage Validation (`hdl/port_analyzer.py`)
```python
class PortAnalyzer:
    def analyze(code):
        
        ┌────────────────────────────────────┐
        │  STEP 1: EXTRACT PORT DEFINITIONS  │
        └────────────────────────────────────┘
        
        1. Parse module declaration:
           module <name> (
               input wire [N:0] port1,
               output reg [M:0] port2,
               ...
           );
        
        2. Extract:
           ├── inputs = [port1, port2, ...]
           └── outputs = [port3, port4, ...]
        
        ┌────────────────────────────────────┐
        │  STEP 2: CHECK PORT USAGE          │
        └────────────────────────────────────┘
        
        For each input port:
            Search in code body for:
            ├── Direct usage: port_name
            ├── In expressions: port_name + ...
            └── In assignments: x = port_name
            
            if NOT found:
                → Add to unused_inputs[]
        
        For each output port:
            Search for assignments:
            ├── assign port_name = ...
            ├── port_name = ...
            └── port_name <= ...
            
            if NOT found:
                → Add to unused_outputs[]
        
        ┌────────────────────────────────────┐
        │  STEP 3: GENERATE FEEDBACK         │
        └────────────────────────────────────┘
        
        Return:
        {
            "all_ports_used": True/False,
            "unused_inputs": [...],
            "unused_outputs": [...],
            "feedback": "Ports X, Y, Z are declared but not used..."
        }
```

### 7.2 Port Refinement Loop
```python
if tests PASSED but ports incomplete:
    
    ┌────────────────────────────────────┐
    │  PORT REFINEMENT SUB-LOOP          │
    └────────────────────────────────────┘
    
    1. Build Port Usage Prompt:
       ├── System instruction
       ├── Current code
       ├── List of unused inputs
       ├── List of unused outputs
       └── Request to use all ports
    
    2. Generate Refined Code:
       └── Call LLM with port usage prompt
    
    3. Write Refined Code:
       └── Overwrite target file
    
    4. Re-run Tests:
       └── Verify code still compiles
    
    5. Re-check Ports:
       └── Analyze port usage again
    
    6. Results:
       ├── If all ports now used AND tests pass:
       │   → SUCCESS! Return (True, refined_code)
       │
       ├── If tests fail after refinement:
       │   → Revert to previous code
       │   → Accept compilation success
       │   → Return (True, original_code)
       │
       └── If refinement failed:
           → Accept compilable code
           → Return (True, original_code)
```

---

## 8. Completion

### 8.1 Success Path
```
✅ Agent completed successfully
├── Final code written to: /code/rtl/<target>.sv
├── All tests passed
├── All ports used (if validation enabled)
└── Return exit code: 0
```

### 8.2 Partial Success Path
```
⚠️ Agent completed with warnings
├── Code generated but tests did not pass
├── Best attempt written to: /code/rtl/<target>.sv
└── Return exit code: 0 (benchmark compatibility)
```

### 8.3 Container Exit
```
1. Agent returns to main.py
2. main.py exits with code 0
3. Docker container terminates
4. run_docker_agent.sh cleanup:
   ├── Remove temporary image
   └── Remove network (if created)
5. Framework reads results from:
   ├── /code/rtl/<target>.sv → Generated code
   └── /code/rundir/agent_detailed.log → Detailed logs
```

---

## 9. Complete Flow Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                    BENCHMARK FRAMEWORK                            │
│  - Creates test harness directory                                │
│  - Generates docker-compose-agent.yml & run_docker_agent.sh      │
│  - Copies task files (prompt.json, testbenches, docs)            │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                  DOCKER CONTAINER STARTS                          │
│  Image: slm-agent-8001                                            │
│  Volumes: docs/, rtl/, verif/, rundir/, prompt.json              │
│  Network: cvdp-bridge-test-agentic_transformed-6461b92b          │
│  Entry: python3 /app/main.py                                      │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    main.py (Entry Point)                          │
│  1. Load configuration from environment                           │
│  2. Create IterativeRefinementAgent(config)                      │
│  3. Call agent.run()                                              │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│               IterativeRefinementAgent.run()                      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Step 1: Read Task from /code/prompt.json                  │  │
│  │         → "Design a 32-bit Brent-Kung parallel adder..."  │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Step 2: Gather Context Files                              │  │
│  │         → docs/spec.md, verif/test_adder.py, etc.         │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Step 3: Find Target File                                  │  │
│  │         → /code/rtl/adder.sv (from TOPLEVEL env)          │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Step 4: Run Refinement Loop (up to 3 iterations)          │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    REFINEMENT LOOP                                │
│  ╔══════════════════════════════════════════════════════════╗    │
│  ║ ITERATION 1                                              ║    │
│  ╚══════════════════════════════════════════════════════════╝    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Build Initial Prompt:                                    │    │
│  │  • System: "You are a Verilog expert..."                │    │
│  │  • Task: "Design 32-bit Brent-Kung adder..."            │    │
│  │  • Context: [docs, testbenches]                          │    │
│  │  • Examples: [few-shot examples]                         │    │
│  └──────────────────────────────────────────────────────────┘    │
│                           │                                       │
│                           ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Call LLM API:                                            │    │
│  │  POST http://host.docker.internal:8001/generate         │    │
│  │  {prompt, max_length=8192, model=granite, temp=0.7}     │    │
│  └──────────────────────────────────────────────────────────┘    │
│                           │                                       │
│                           ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Extract & Validate Code:                                │    │
│  │  • Find ```verilog ... ``` block                        │    │
│  │  • Check module/endmodule                               │    │
│  │  • Validate parentheses                                  │    │
│  │  • Write to /code/rtl/adder.sv                          │    │
│  └──────────────────────────────────────────────────────────┘    │
│                           │                                       │
│                           ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Run Tests:                                               │    │
│  │  1. Lint Check: verilator --lint-only adder.sv         │    │
│  │     → Compilation: ✅ PASS / ❌ FAIL                     │    │
│  │  2. CocoTB Test: python test_adder.py (if exists)      │    │
│  │     → Testbench: ✅ PASS / ❌ FAIL / ⚠️ N/A              │    │
│  └──────────────────────────────────────────────────────────┘    │
│                           │                                       │
│            ┌──────────────┴──────────────┐                       │
│            ▼                              ▼                       │
│    ┌──────────────┐              ┌──────────────┐                │
│    │ Tests PASS   │              │ Tests FAIL   │                │
│    └──────┬───────┘              └──────┬───────┘                │
│           │                              │                        │
│           ▼                              ▼                        │
│  ┌──────────────────┐          ┌────────────────────┐           │
│  │ Port Validation  │          │ Categorize Errors  │           │
│  │  • Check unused  │          │  → syntax          │           │
│  │    inputs/outputs│          │  → undeclared      │           │
│  │                  │          │  → width           │           │
│  │ All ports used?  │          │  → ...             │           │
│  └────┬────────┬────┘          └─────────┬──────────┘           │
│       │        │                          │                       │
│   YES │        │ NO                       │                       │
│       ▼        ▼                          ▼                       │
│   ┌──────┐  ┌──────────────┐    ┌─────────────────┐            │
│   │SUCCESS│  │Port Refinement│    │ ITERATION 2     │            │
│   │RETURN │  │Sub-loop       │    │ (Refinement     │            │
│   └──────┘  │ • Build prompt│    │  Prompt)        │            │
│              │ • Refine code │    └────────┬────────┘            │
│              │ • Re-test     │             │                      │
│              └───────┬───────┘             │                      │
│                      │                     │                      │
│                      ▼                     ▼                      │
│                  ┌───────┐         ╔═══════════════╗             │
│                  │SUCCESS│         ║ ITERATION 3   ║             │
│                  │RETURN │         ║ (if needed)   ║             │
│                  └───────┘         ╚═══════════════╝             │
│                                            │                      │
│                                            ▼                      │
│                                    ┌──────────────┐              │
│                                    │ Max iterations│              │
│                                    │ Return best  │              │
│                                    │ attempt      │              │
│                                    └──────────────┘              │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                     AGENT COMPLETION                              │
│  • Write final code to /code/rtl/adder.sv                        │
│  • Log detailed execution to /code/rundir/agent_detailed.log     │
│  • Return exit code 0 to main.py                                 │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                  CONTAINER EXITS CLEANLY                          │
│  • Docker container terminates                                    │
│  • Cleanup script removes resources                               │
│  • Framework collects generated code and logs                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## 10. Key Components Summary

### 10.1 Component Interactions

```
┌──────────────┐     Reads      ┌──────────────┐
│ CodeManager  │◄───────────────│ prompt.json  │
│              │                │ context files│
└──────┬───────┘                └──────────────┘
       │ provides task/context
       ▼
┌──────────────┐     Builds     ┌──────────────┐
│PromptBuilder │───────────────►│ Optimized    │
│              │                │ Prompts      │
└──────────────┘                └──────┬───────┘
                                       │
                                       ▼
                                ┌──────────────┐
                                │ SLMAPIClient │
                                │ (LLM API)    │
                                └──────┬───────┘
                                       │
                                       ▼
                                ┌──────────────┐
                                │ResponseParser│
                                │ (Extract HDL)│
                                └──────┬───────┘
                                       │
                                       ▼
┌──────────────┐     Writes     ┌──────────────┐
│ CodeManager  │───────────────►│ /code/rtl/   │
│              │                │ target.sv    │
└──────────────┘                └──────┬───────┘
                                       │
                                       ▼
                                ┌──────────────┐
                                │ TestRunner   │
                                │ (Lint+CocoTB)│
                                └──────┬───────┘
                                       │
                        ┌──────────────┼──────────────┐
                        ▼              ▼              ▼
                 ┌──────────┐   ┌──────────┐   ┌──────────┐
                 │LintRunner│   │CocotbRnr │   │PortAnlzr │
                 │(Verilator)   │(Tests)   │   │(Validate)│
                 └──────────┘   └──────────┘   └──────────┘
                        │              │              │
                        └──────────────┴──────────────┘
                                       │
                                       ▼
                                ┌──────────────┐
                                │RefinementLoop│
                                │ (Coordinate) │
                                └──────────────┘
```

### 10.2 File Locations Inside Container

```
Container Filesystem:
/app/                           ← Agent code (read-only)
├── main.py                     ← Entry point
├── config/settings.py          ← Configuration
├── core/
│   ├── agent.py                ← Main coordinator
│   └── refinement_loop.py      ← Iteration logic
├── llm/
│   ├── api_client.py           ← LLM communication
│   └── response_parser.py      ← Code extraction
├── prompts/
│   ├── prompt_builder.py       ← Prompt construction
│   └── templates.py            ← Prompt templates
├── hdl/
│   ├── code_manager.py         ← File I/O
│   └── port_analyzer.py        ← Port validation
└── testing/
    ├── test_runner.py          ← Test orchestration
    ├── cocotb_runner.py        ← CocoTB tests
    └── lint_runner.py          ← Verilator/Icarus

/code/                          ← Mounted volumes (read/write)
├── prompt.json                 ← Task description
├── docs/                       ← Documentation
├── rtl/                        ← Target directory for generated code
├── verif/                      ← Testbenches
├── rundir/                     ← Logs and runtime files
└── src/.env                    ← Environment variables
```

---

## 11. Environment Variables

```bash
# Inside Container (set in Dockerfile):
PYTHONPATH=/app                          # Python module search path
SLM_API_URL=http://host.docker.internal:8001  # LLM service endpoint
SLM_MODEL=granite                        # Model identifier
SLM_MAX_LENGTH=8192                      # Max tokens for generation
SLM_TIMEOUT=3000                         # API request timeout (seconds)

# From mounted .env file (read by CodeManager, not main.py):
TOPLEVEL=adder                           # Module name to generate
                                         # Used by: CodeManager.get_expected_filename()
                                         #          to determine target file: adder.sv

# Set by CocoTB runner during test execution:
VERILOG_SOURCES=/code/rtl/*.sv          # RTL files for testing
TOPLEVEL_LANG=verilog                    # HDL language
SIM=icarus                               # Simulator (Icarus Verilog)
```

---

## 12. Log Files

```
/code/rundir/agent_detailed.log          ← Main agent log
  Contains:
  • Initialization messages
  • Configuration details
  • Iteration progress
  • Prompt/response content
  • Test results
  • Port validation feedback
  • Error messages
  • Success/failure status

Console output (Docker logs):
  • Prompt sent to SLM (each iteration)
  • Response from SLM
  • Extracted code
  • Test execution results
```

---

## 13. Error Handling

### 13.1 Graceful Degradation
```
• LLM API failure → Keep previous code, continue
• Code extraction failure → Retry next iteration
• Basic validation failure → Continue with error feedback
• Compilation failure → Provide errors to refinement
• Test failure (but compiles) → Provide test output to refinement
• Port validation failure → Attempt port refinement sub-loop
• Max iterations reached → Return best attempt, exit code 0
```

### 13.2 Always Exit Cleanly
```
The agent ALWAYS returns exit code 0, even on failure.
This is intentional for benchmark compatibility:
  • Framework determines success based on generated code quality
  • Non-zero exit codes could halt benchmark processing
  • Failures are logged but don't crash the system
```

---

## 14. Summary

**The complete flow is:**

1. **Framework** prepares test environment with task files
2. **Docker** container starts with agent code and mounted volumes
3. **main.py** initializes agent with configuration
4. **Agent** reads task, gathers context, finds target file
5. **Refinement Loop** iteratively generates and tests code:
   - Build optimized prompt (initial or refinement)
   - Call LLM API to generate code
   - Extract and validate Verilog code
   - Write to target file
   - Run lint checks (compilation)
   - Run testbench (if available)
   - Validate port usage (if enabled)
   - Refine based on feedback
6. **Completion** writes final code and logs, exits cleanly
7. **Framework** collects results and evaluates quality

The system is designed to be **robust**, **iterative**, and **benchmark-friendly**, with multiple validation layers and graceful error handling.

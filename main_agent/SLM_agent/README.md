# SLM Agent - Modular Architecture

**Iterative Refinement Agent for Verilog Code Generation using Small Language Models**

## Overview

This is a modularized, production-ready implementation of an SLM agent that generates Verilog/SystemVerilog code through iterative refinement with comprehensive validation.

### Key Features

✅ **Modular Architecture**: 15+ modules organized in 7 packages  
✅ **I/O Port Usage Validation**: NEW feature that ensures all ports are used  
✅ **SLM-Optimized Prompts**: Keywords and templates optimized for small language models  
✅ **Context Optimization**: Smart prioritization and token budget management  
✅ **Error Categorization**: Structured feedback for faster convergence  
✅ **Extensible Design**: Easy to add new SLM backends, validators, or test runners  

## Architecture

```
slm_agent/
├── __init__.py
├── main.py                     # Entry point
├── README.md                   # This file
│
├── config/                     # Configuration management
│   ├── __init__.py
│   └── settings.py             # AgentConfig with validation
│
├── core/                       # Core orchestration
│   ├── __init__.py
│   ├── agent.py                # Main coordinator
│   └── refinement_loop.py      # Iteration management + port validation
│
├── llm/                        # Language model interface
│   ├── __init__.py
│   ├── api_client.py           # SLM API client
│   └── response_parser.py      # Code extraction & validation
│
├── prompts/                    # Prompt engineering
│   ├── __init__.py
│   ├── templates.py            # SLM-optimized templates with keywords
│   └── prompt_builder.py       # Dynamic prompt assembly
│
├── hdl/                        # HDL-specific operations
│   ├── __init__.py
│   ├── code_manager.py         # File I/O & context gathering
│
├── testing/                    # Test execution
│   ├── __init__.py
│   ├── test_runner.py          # Test orchestration
│   └── lint_runner.py          # Verilator/Icarus linting
│
└── utils/                      # Utilities
    ├── __init__.py
    └── logger.py               # Dual-output logging
```

## Usage

### Basic Usage

```python
from slm_agent.main import main

# Run with default configuration
exit_code = main()
```

### Advanced Usage

```python
from slm_agent.core.agent import IterativeRefinementAgent
from slm_agent.config.settings import AgentConfig

# Custom configuration
config = AgentConfig(
    max_iterations=5,
    slm_model="deepseek",
    enable_port_validation=True,
    use_few_shot_examples=True
)

# Create and run agent
agent = IterativeRefinementAgent(config)
exit_code = agent.run()
```

## Configuration

Configuration via environment variables or `AgentConfig`:

```python
@dataclass
class AgentConfig:
    # Iteration settings
    max_iterations: int = 3
    early_exit_on_success: bool = True
    
    # SLM API settings
    slm_api_url: str = "http://host.docker.internal:8000"
    slm_model: str = "deepseek"
    slm_max_length: int = 8192
    slm_timeout: int = 300
    
    # Prompt engineering
    use_few_shot_examples: bool = True
    max_context_files: int = 10
    enable_port_validation: bool = True  # NEW
    
    # Testing
    test_timeout: int = 120
    lint_timeout: int = 30
```

Environment variables:
- `SLM_API_URL`: SLM API endpoint
- `SLM_MODEL`: Model identifier
- `SLM_MAX_LENGTH`: Maximum generation length
- `SLM_TIMEOUT`: Request timeout

## Key Components

### 1. Port Analyzer (NEW Feature)

Validates that all module ports are actually used in the implementation:

```python
from slm_agent.hdl.port_analyzer import PortAnalyzer

analyzer = PortAnalyzer()
result = analyzer.analyze(verilog_code)

# Result structure:
# {
#     "all_ports_used": bool,
#     "unused_inputs": List[str],
#     "unused_outputs": List[str],
#     "port_usage": Dict[str, str],
#     "feedback": str
# }
```

**How it works:**
1. Parses module interface to extract input/output ports
2. Scans module body for port references
3. For inputs: Checks if port appears in expressions
4. For outputs: Checks if port is assigned (<=, =, or assign)
5. Generates detailed feedback for refinement

### 2. Enhanced Prompt Engineering

**SLM-Optimized Keywords:**
- `TASK`, `REQUIREMENTS`, `SPECIFICATIONS`
- `GENERATE`, `IMPLEMENT`, `FIX`, `CORRECT`
- `CONSTRAINTS`, `RULES`, `MUST`
- `ERROR`, `WARNING`, `ISSUE`

**Few-Shot Examples:**
- Automatically selected based on task keywords
- Includes: counter, FIFO, FSM patterns
- Demonstrates best practices

### 3. Refinement Workflow

```
1. Generate initial code (with few-shot examples)
2. Write to target file
3. Run compilation tests
4. If pass → Check port usage (NEW)
5. If ports incomplete → Refine with port feedback
6. If all good → Success!
7. If fail → Refine with error feedback
8. Repeat up to max_iterations
```

### 4. Error Categorization

Automatically categorizes errors for targeted refinement:
- `syntax`: Parse errors, unexpected tokens
- `undeclared`: Undefined variables/signals
- `type`: Type mismatches
- `width`: Bit width issues
- `latch`: Latch inference warnings
- `timing`: Timing violations

## Prompt Templates

### Initial Generation
```
ROLE: Expert Verilog/SystemVerilog RTL Designer

TASK: Generate Verilog/SystemVerilog RTL code

REQUIREMENTS:
{task_description}

CONTEXT FILES:
{context_files}

DESIGN PATTERNS (Examples):
{few_shot_examples}

OUTPUT FORMAT:
- Start with: module <name>
- Declare all ports with proper types
- Include proper reset logic
- Use non-blocking (<=) for sequential logic
- Use blocking (=) for combinational logic
- End with: endmodule

GENERATE: Complete synthesizable RTL code below
```

### Port Usage Refinement (NEW)
```
TASK: Complete port usage in Verilog module

CURRENT CODE (compiles but incomplete):
```verilog
{current_code}
```

PORT USAGE ANALYSIS:
- UNUSED INPUT PORTS: {unused_inputs}
- UNUSED OUTPUT PORTS: {unused_outputs}

REQUIREMENTS:
- MUST use all input ports in internal logic
- MUST assign all output ports
- PRESERVE existing correct functionality
- ADD necessary logic for unused ports

GENERATE: Complete RTL code with all ports properly used
```

## Testing

The agent supports multiple testing backends:

1. **CocoTB Tests** (preferred)
   - pytest-based verification
   - Comprehensive functional testing

2. **Verilator** (fallback)
   - Fast lint checking
   - Syntax validation

3. **Icarus Verilog** (fallback)
   - Open-source simulator
   - Basic syntax checks

## Extending the Agent

### Adding a New SLM Backend

```python
# In llm/api_client.py
class CustomSLMClient(SLMAPIClient):
    def generate(self, prompt: str, temperature: float = 0.7):
        # Custom API implementation
        pass
```

### Adding a New Validator

```python
# In hdl/
class CustomValidator:
    def validate(self, code: str) -> Tuple[bool, str]:
        # Custom validation logic
        return success, errors
```

### Adding a New Test Runner

```python
# In testing/
class CustomTestRunner:
    def run(self) -> Tuple[bool, str]:
        # Custom test execution
        return success, errors
```

## Benefits Over Monolithic Design

| Aspect | Monolithic | Modular |
|--------|-----------|---------|
| **Maintainability** | 600+ line single file | 15+ focused modules |
| **Testability** | Hard to unit test | Each module testable |
| **Extensibility** | Requires major refactoring | Add new modules easily |
| **Reusability** | Tightly coupled | Loosely coupled components |
| **Debugging** | Complex stack traces | Clear component boundaries |
| **Configuration** | Hard-coded values | Centralized config |
| **Validation** | Compilation only | Compilation + semantics |

## Performance Optimizations

1. **Context Prioritization**: docs > rtl > verif
2. **Token Budget Management**: 40% task, 40% context, 20% examples
3. **File Truncation**: Large files truncated to 2000 chars
4. **Early Exit**: Stop on first success
5. **Temperature Strategies**: Lower for interfaces, higher for logic

## Future Enhancements

### Planned Features
- Multi-stage generation (interface → logic → assertions)
- Temperature strategies per generation stage
- Self-consistency with voting
- RAG with vector database for design patterns
- Constrained decoding at token level
- Automated test generation

## References

- IEEE 1800-2017 SystemVerilog Standard
- SLM Prompt Engineering Best Practices
- ASIC Design Flow Documentation
- CocoTB Testing Framework

## License

SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.  
SPDX-License-Identifier: Apache-2.0

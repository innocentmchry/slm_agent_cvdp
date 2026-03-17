#!/usr/bin/env python3
"""Prompt templates similar to default"""

# System prompt with role definition
SYSTEM_PROMPT = """You are a helpful agentic ai assistant.
Consider that you have a folder structure like the following:

    - rtl/*   : Contains files which are RTL code.
    - docs/*  : Contains files used to document the project, like Block Guides, RTL Plans and Verification Plans.

"""


CATEGORY = {
    "2": """You are solving an 'RTL Code Completion' problem. To solve this problem correctly, you should only respond with the RTL code generated according to the requirements.""",
    "3": """You are solving a 'Specification to RTL Translation' problem. To solve this problem correctly, you should only respond with the RTL code translated from the specification.""",
    "4": """You are solving an 'RTL Code Modification' problem. To solve this problem correctly, you should only respond with the modified RTL code according to the requirements.""",
    "5": """You are solving a 'Specification to RTL Translation: Module Instantiation and Component Reuse' problem. To solve this problem correctly, you should only respond with the RTL code translated from the specification and with proper module instantiation and component reuse.""",
    "6": """You are solving an 'RTL Correspondence' problem. To solve this problem correctly, you should only respond with a verbatim quote from the specification (if the context is RTL) that corresponds to the RTL code snippet or verbatim RTL source code (if the context is specification) that corresponds to the specification snippet.""",
    "7": """You are solving an 'RTL Lint Improvement or Power-Performance Optimization' problem. To solve this problem correctly, you should only respond with improved RTL code to address lint issues or optimize for power/performance.""",
    "8": """You are solving a 'Testbench Correspondence' problem. To solve this problem correctly, you should only respond with the verbatim testbench code that corresponds to the test plan snippet (if the context is testbench code) or verbatim test plan that corresponds to the testbench code snippet (if the context is testbench code).""",
    "9": """You are solving a 'Question & Answer on RTL' problem. To solve this problem correctly, you should only respond with a detailed answer to the question about RTL.""",
    "10": """You are solving a 'Question & Answer on Testbench' problem. To solve this problem correctly, you should only respond with a detailed answer to the question about the testbench.""",
    "12": """You are solving a 'Test Plan to Testbench Stimulus Generation' problem. To solve this problem correctly, you should only respond with the testbench stimulus code generated based on the test plan specification.""",
    "13": """You are solving a 'Test Plan to Testbench Checker Generation' problem. To solve this problem correctly, you should only respond with the testbench checker code generated based on the test plan specification.""",
    "14": """You are solving a 'Test Plan to Assertions Generation' problem. To solve this problem correctly, you should only respond with the assertions for the testbench based on the test plan specification.""",
    "16": """You are solving an 'RTL Debugging and Bug Fixing' problem. To solve this problem correctly, you should only respond with the RTL code that is debugged and fixed to address the bug."""
}

# Initial generation template
INITIAL_GENERATION_TEMPLATE = """{system_prompt}

{category_description}
{context_files}
Provide me one answer for this request: {task_description}

"""

# Refinement template for syntax or compilation errors
REFINEMENT_TEMPLATE_1 = """{system_prompt}
{category_description}
{context_files}
Provide me one answer for this request: {task_description}

You had previously generated this code:
{previous_code}

Your previous code generation had compilation errors as follows:
{error_messages}

Based on the initial request and context files and your generated code provide me one answer fix.

INSTRUCTIONS:
- ANALYZE: Identify root cause of each error
- ANALYZE: Initial context files and your generated code to find potential issues
- PRESERVE: Keep working parts unchanged
- OUTPUT: Full corrected code (not diff/patch)

CRITICAL INSTRUCTIONS:
- Output ONLY the corrected Verilog module code
- Do NOT include explanations or reasoning text
- Start your response immediately with "module"
- Do NOT write analysis or thinking steps before the code

"""

REFINEMENT_TEMPLATE_2 = """{system_prompt}
{category_description}
{context_files}
Provide me one answer for this request: {task_description}

You had previously generated this code:
{previous_code}

Your previous code generation had testbench errors:
The testbench wont be provided but you have to analyse why testbench is failing.
Based on the initial request and context files and your generated code provide me one answer fix.

INSTRUCTIONS:
- ANALYZE: Identify root cause of each error
- ANALYZE: Initial context files and your generated code to find potential issues
- PRESERVE: Keep working parts unchanged
- OUTPUT: Full corrected code (not diff/patch)

CRITICAL INSTRUCTIONS:
- Output ONLY the corrected Verilog module code
- Do NOT include explanations or reasoning text
- Start your response immediately with "module"
- Do NOT write analysis or thinking steps before the code

"""

REFINEMENT_TEMPLATE_3 = """{system_prompt}
{category_description}
{context_files}
Provide me one answer for this request: {task_description}

You had previously generated this code:
{previous_code}

Your previous code generation had compilation warnings:
{warning_messages}

Your previous code generation had testbench errors:
The testbench wont be provided but you have to analyse why testbench is failing.
Based on the initial request and context files and your generated code provide me one answer fix.

INSTRUCTIONS:
- ANALYZE: Identify root cause of each error
- ANALYZE: Initial context files and your generated code to find potential issues
- PRESERVE: Keep working parts unchanged
- OUTPUT: Full corrected code (not diff/patch)

CRITICAL INSTRUCTIONS:
- Output ONLY the corrected Verilog module code
- Do NOT include explanations or reasoning text
- Start your response immediately with "module"
- Do NOT write analysis or thinking steps before the code

"""


# Refinement template for syntax/compilation errors
REFINEMENT_TEMPLATE = """{system_prompt}

TASK: Fix compilation/test errors in Verilog code

ORIGINAL REQUIREMENTS:
{task_description}

PREVIOUS CODE (Iteration {iteration}):
```verilog
{previous_code}
```

ERRORS DETECTED:
```
{error_messages}
```

ERROR CATEGORY: {error_category}
{test_context}

INSTRUCTIONS:
- ANALYZE: Identify root cause of each error
- FIX: Correct the specific errors listed above
- PRESERVE: Keep working parts unchanged
- VERIFY: Ensure all fixes are complete
- OUTPUT: Full corrected code (not diff/patch)

CRITICAL INSTRUCTIONS:
- Output ONLY the corrected Verilog module code
- Do NOT include explanations or reasoning text
- Start your response immediately with "module"
- Do NOT write analysis or thinking steps before the code
- If test code is provided, ensure your implementation matches test expectations

GENERATE THE FIXED MODULE CODE NOW:"""


# Port usage refinement template (NEW)
PORT_USAGE_TEMPLATE = """{system_prompt}

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

CONSTRAINTS:
- Do NOT remove port declarations
- Integrate unused ports meaningfully
- Maintain module interface contract

GUIDANCE:
- Unused inputs: Use in conditional logic, counters, or state machines
- Unused outputs: Assign based on inputs or internal state

GENERATE: Complete RTL code with all ports properly used"""


# Few-shot examples with common patterns
FEW_SHOT_EXAMPLES = {
    "counter": """
EXAMPLE: Parameterized Counter
```verilog
module counter #(
    parameter WIDTH = 8
)(
    input  logic             clk,
    input  logic             rst_n,
    input  logic             enable,
    output logic [WIDTH-1:0] count
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            count <= '0;
        else if (enable)
            count <= count + 1'b1;
    end
endmodule
```""",
    
    "fifo": """
EXAMPLE: Synchronous FIFO
```verilog
module sync_fifo #(
    parameter DEPTH = 8,
    parameter WIDTH = 32
)(
    input  logic             clk,
    input  logic             rst_n,
    input  logic             wr_en,
    input  logic             rd_en,
    input  logic [WIDTH-1:0] wr_data,
    output logic [WIDTH-1:0] rd_data,
    output logic             full,
    output logic             empty
);
    logic [WIDTH-1:0] mem [0:DEPTH-1];
    logic [$clog2(DEPTH):0] wr_ptr, rd_ptr;
    
    assign full  = (wr_ptr[$clog2(DEPTH)] != rd_ptr[$clog2(DEPTH)]) &&
                   (wr_ptr[$clog2(DEPTH)-1:0] == rd_ptr[$clog2(DEPTH)-1:0]);
    assign empty = (wr_ptr == rd_ptr);
    
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
        end else begin
            if (wr_en && !full)
                wr_ptr <= wr_ptr + 1'b1;
            if (rd_en && !empty)
                rd_ptr <= rd_ptr + 1'b1;
        end
    end
    
    always_ff @(posedge clk) begin
        if (wr_en && !full)
            mem[wr_ptr[$clog2(DEPTH)-1:0]] <= wr_data;
    end
    
    assign rd_data = mem[rd_ptr[$clog2(DEPTH)-1:0]];
endmodule
```""",
    
    "fsm": """
EXAMPLE: Finite State Machine
```verilog
module fsm (
    input  logic clk,
    input  logic rst_n,
    input  logic start,
    input  logic done,
    output logic busy,
    output logic valid
);
    typedef enum logic [1:0] {
        IDLE = 2'b00,
        ACTIVE = 2'b01,
        FINISH = 2'b10
    } state_t;
    
    state_t current_state, next_state;
    
    // State register
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            current_state <= IDLE;
        else
            current_state <= next_state;
    end
    
    // Next state logic
    always_comb begin
        next_state = current_state;
        case (current_state)
            IDLE: if (start) next_state = ACTIVE;
            ACTIVE: if (done) next_state = FINISH;
            FINISH: next_state = IDLE;
            default: next_state = IDLE;
        endcase
    end
    
    // Output logic
    assign busy = (current_state == ACTIVE);
    assign valid = (current_state == FINISH);
endmodule
```"""
}


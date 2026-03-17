#!/usr/bin/env python3
"""Prompt templates with SLM-optimized keywords"""

# System prompt with role definition
SYSTEM_PROMPT = """ROLE: Expert Verilog/SystemVerilog RTL Designer

EXPERTISE:
- Synthesizable HDL code generation
- IEEE 1800-2017 SystemVerilog standard
- ASIC/FPGA design best practices
- Clock domain crossing
- Reset methodology
- Timing closure

CONSTRAINTS:
- MUST generate syntactically correct code
- MUST use all declared input/output ports
- MUST include proper reset logic
- MUST avoid combinational loops
- MUST use meaningful signal names
- MUST follow coding standards"""


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


# Initial generation template
INITIAL_GENERATION_TEMPLATE = """{system_prompt}

TASK: Generate Verilog/SystemVerilog RTL code

REQUIREMENTS:
{task_description}

CONTEXT FILES:
{context_files}

{few_shot_examples}

OUTPUT FORMAT:
- Start with: module <name>
- Declare all ports with proper types
- Include proper reset logic
- Use non-blocking (<=) for sequential logic
- Use blocking (=) for combinational logic
- End with: endmodule

CRITICAL INSTRUCTIONS:
- Output ONLY the Verilog module code
- Do NOT include explanations, reasoning, or comments outside the module
- Start your response immediately with "module"
- Do NOT write thinking steps before the code
- Do NOT explain your approach before generating code

REQUIRED FORMAT:
module <name> (
    // port declarations
);
    // internal logic
endmodule

GENERATE THE MODULE CODE NOW:"""


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

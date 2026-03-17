#!/usr/bin/env python3
"""
Test script to demonstrate the flag parameter usage in run_benchmark.py

This script shows how to use flag=0 (create only) and flag=1 (execute only)
for the all_run() method.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_flag_usage():
    """
    Demonstrates the two-phase execution pattern:
    1. Phase 1: Create harness scripts (flag=0)
    2. Phase 2: Execute harness scripts (flag=1)
    """
    print("=" * 80)
    print("FLAG PARAMETER USAGE DEMONSTRATION")
    print("=" * 80)
    
    print("\n### Phase 1: Create Harness Scripts (flag=0) ###")
    print("""
# This phase will:
# - Create run_docker_harness_*.sh scripts
# - Configure Docker networks in scripts
# - Skip actual execution
# - Return results with 'skipped': True

res = self.repo.all_run(self.model, flag=0)
print(f"Phase 1 complete. Scripts created, execution skipped.")
print(f"Number of datapoints processed: {len(res)}")
    """)
    
    print("\n### Phase 2: Execute Harness Scripts (flag=1) ###")
    print("""
# This phase will:
# - Execute the previously created run_docker_harness_*.sh scripts
# - Collect test results
# - Generate logs
# - Return actual test results

res = self.repo.all_run(self.model, flag=1)
print(f"Phase 2 complete. Tests executed.")
print(f"Number of datapoints tested: {len(res)}")
    """)
    
    print("\n### Default Behavior (flag=1 by default) ###")
    print("""
# Default behavior creates scripts AND executes them in one step:

res = self.repo.all_run(self.model)
# This is equivalent to:
# res = self.repo.all_run(self.model, flag=1)
    """)
    
    print("\n" + "=" * 80)
    print("CALL CHAIN WITH FLAG PARAMETER")
    print("=" * 80)
    print("""
run_benchmark.py:
    res = obj.repo.all_run(model, flag=0)  # or flag=1
    
dataset_processor.py:
    def all_run(self, model, flag=1):
        executor.execute_parallel_with_results(
            task_func=self.th_run,
            task_args=[model, flag]
        )
    
    def th_run(self, id, q, model, flag=1):
        res = self.run(id, obj, repo, model, flag)
    
    def run(self, id, obj, repo, model, flag=1):
        (tests, errors) = repo.obj(flag=flag)

repository.py:
    def obj(self, uut, flag=1):
        result = self.obj_harness(issue_path, logfile, uut, flag=flag)
    
    def obj_harness(self, issue_path, logfile, uut, flag=1):
        result = self.log_docker(docker, opts, service, service_log, flag=flag)
    
    def log_docker(self, docker, cmd, service, logfile, monitor_size=True, flag=1):
        # Create the run_docker_harness_*.sh script
        if flag == 0:
            # Skip execution, return early
            return {"result": 0, "log": logfile, "skipped": True}
        # Execute the script
        result = self.log_run(line_cmd, kill_cmd, logfile)
        return result
    """)

def test_single_issue_usage():
    """
    Demonstrates flag usage for single issue execution
    """
    print("\n" + "=" * 80)
    print("SINGLE ISSUE EXECUTION WITH FLAG")
    print("=" * 80)
    print("""
# Example: Execute a single datapoint with flag parameter

# Create harness script only (flag=0)
result = obj.execute_single(issue_id="cvdp_copilot_32_bit_Brent_Kung_PP_adder")
# To use flag parameter, modify execute_single to pass it through:
# result = self.repo.run(issue, obj, repo, self.model, flag=0)

# Execute harness script only (flag=1)
# result = self.repo.run(issue, obj, repo, self.model, flag=1)
    """)

def show_return_values():
    """
    Show the different return values based on flag
    """
    print("\n" + "=" * 80)
    print("RETURN VALUES BASED ON FLAG")
    print("=" * 80)
    
    print("\n### flag=0 (Create Only) ###")
    print("""
Return value structure:
{
    "result": 0,
    "log": "<logfile_path>",
    "error_msg": None,
    "execution": 0,
    "pid": None,
    "skipped": True
}
    """)
    
    print("\n### flag=1 (Execute) ###")
    print("""
Return value structure:
{
    "result": <exit_code>,
    "log": "<logfile_path>",
    "error_msg": <error_message_or_None>,
    "execution": <execution_time_seconds>,
    "pid": <process_id>
}
    """)

if __name__ == "__main__":
    test_flag_usage()
    test_single_issue_usage()
    show_return_values()
    
    print("\n" + "=" * 80)
    print("For more details, see USAGE_FLAG_EXAMPLE.md")
    print("=" * 80)

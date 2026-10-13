#!/usr/bin/env python3
"""Iterative refinement loop with port usage validation"""

import logging
import time
from typing import Tuple, Optional, Dict
from pathlib import Path

logger = logging.getLogger(__name__)


class RefinementLoop:
    """Manage iterative code refinement with validation"""
    
    def __init__(
        self,
        llm_client,
        prompt_builder,
        code_manager,
        response_parser,
        port_analyzer,
        test_runner,
        max_iterations: int,
        enable_port_validation: bool,
        metrics=None
    ):
        """
        Initialize refinement loop
        
        Args:
            llm_client: SLM API client
            prompt_builder: Prompt builder
            code_manager: Code manager
            response_parser: Response parser
            port_analyzer: Port analyzer
            test_runner: Test runner
            max_iterations: Maximum refinement iterations
            enable_port_validation: Enable port usage validation
            metrics: Optional MetricsRecorder for per-iteration outcomes
        """
        self.llm_client = llm_client
        self.prompt_builder = prompt_builder
        self.code_manager = code_manager
        self.response_parser = response_parser
        self.port_analyzer = port_analyzer
        self.test_runner = test_runner
        self.max_iterations = max_iterations
        self.enable_port_validation = enable_port_validation
        self.metrics = metrics
        
        self.iteration = 0
        self.code = None
        self.errors = None
        self.warnings = None
        self.compilation_success = False
        self.test_success = False
    
    def run(self, task: str, context: Dict[str, str], target_file: Path) -> Tuple[bool, Optional[str]]:
        """
        Execute refinement loop
        
        Args:
            task: Task description
            context: Context files
            target_file: Target file path
            
        Returns:
            Tuple of (success, final_code)
        """
        for self.iteration in range(1, self.max_iterations + 1):
            logger.info("=" * 80)
            logger.info(f"ITERATION {self.iteration}/{self.max_iterations}")
            logger.info("=" * 80)
            
            if self.metrics:
                self.metrics.start_iteration(self.iteration, "initial" if self.iteration == 1 else "refinement")

            # Build appropriate prompt
            if self.iteration == 1:
                prompt = self.prompt_builder.build_initial_prompt(task, context)
            else:
                # error_category = self.test_runner.categorize_errors(self.errors)

                prompt = self.prompt_builder.build_refinement_prompt(
                    task, context, self.code, self.warnings, self.errors, self.iteration, self.compilation_success, self.test_success
                )
            
            # Print prompt for debugging
            print("\n" + "=" * 80)
            print(f"PROMPT SENT TO SLM (Iteration {self.iteration}):")
            print("=" * 80)
            # print(prompt[:2000] + "..." if len(prompt) > 2000 else prompt)
            print(prompt)
            print("=" * 80 + "\n")
            
            # Generate code
            response = self.llm_client.generate(prompt)
            if self.metrics:
                self.metrics.update_iteration(llm_success=bool(response))
            if not response:
                logger.error("LLM generation failed")
                if self.code:  # Keep previous code
                    logger.info("Keeping previous code")
                    continue
                else:
                    return False, None
            
            # Print response for debugging
            print("\n" + "=" * 80)
            print(f"RESPONSE FROM SLM (Iteration {self.iteration}):")
            print("=" * 80)

            # truncated_response = response[:16000] + "..." if len(response) > 16000 else response

            # print(truncated_response)
            print(response)
            print("=" * 80 + "\n")
            
            # Extract and validate code
            self.code = self.response_parser.extract_verilog(response)
            
            structure_valid = self.response_parser.validate_basic_structure(self.code)
            if self.metrics:
                self.metrics.update_iteration(structure_valid=bool(structure_valid))
            if not structure_valid:
                logger.warning("Code failed basic structure validation")
                self.errors = "Code structure validation failed: missing module/endmodule or unbalanced parentheses"
                continue

            self.code = self.response_parser.validate_module_name(self.code)
            
            # Print extracted code
            print("\n" + "=" * 80)
            print(f"EXTRACTED CODE (Iteration {self.iteration}):")
            print("=" * 80)
            print(self.code)
            print("=" * 80 + "\n")
            
            
            
            # Run tests
            logger.info("Running compilation test and Checking if test case(s) pass")
            test_start = time.time()
            self.compilation_success, self.test_success, self.warnings, self.errors = self.test_runner.run(self.code)
            if self.metrics:
                self.metrics.update_iteration(
                    compilation_success=bool(self.compilation_success),
                    test_success=bool(self.test_success),
                    test_time_ms=round((time.time() - test_start) * 1000, 1)
                )

            # Write code only if compilation succeeded.
            if self.compilation_success:         
                logger.info("Code compiles successfully. Saving to file.")  
                if not self.code_manager.write_code(target_file, self.code):
                    logger.error("Failed to write code")
                    return False, None
            else:
                logger.warning("Code failed to compile. Not writing to file.")


            # Determine if we should exit early or continue iterating
            # Only exit early if actual testbench passed (not just compilation)
            should_exit_early = self.test_success
            
            if self.test_success:
                # # Tests passed! Now check port usage if enabled
                # if self.enable_port_validation:
                #     logger.info("Checking port usage...")
                #     port_result = self.port_analyzer.analyze(self.code)
                    
                #     if not port_result["all_ports_used"]:
                #         logger.warning("Code compiles but ports are incomplete!")
                #         logger.info(port_result["feedback"])
                        
                #         # Build port usage refinement prompt
                #         port_prompt = self.prompt_builder.build_port_usage_prompt(
                #             self.code,
                #             port_result["unused_inputs"],
                #             port_result["unused_outputs"]
                #         )
                        
                #         # Print port usage prompt
                #         print("\n" + "=" * 80)
                #         print(f"PORT USAGE REFINEMENT PROMPT (Iteration {self.iteration}):")
                #         print("=" * 80)
                #         #print(port_prompt[:2000] + "..." if len(port_prompt) > 2000 else port_prompt)
                #         print(prompt)
                #         print("=" * 80 + "\n")
                        
                #         # Generate refined code with port usage
                #         port_response = self.llm_client.generate(port_prompt)
                        
                #         if port_response:
                #             refined_code = self.response_parser.extract_verilog(port_response)
                            
                #             # Write refined code
                #             self.code_manager.write_code(target_file, refined_code)
                            
                #             # Re-run tests
                #             retest_success, retest_errors = self.test_runner.run()
                            
                #             if retest_success:
                #                 # Check ports again
                #                 port_recheck = self.port_analyzer.analyze(refined_code)
                                
                #                 if port_recheck["all_ports_used"]:
                #                     logger.info("=" * 80)
                #                     logger.info(f"SUCCESS ON ITERATION {self.iteration} (after port refinement)!")
                #                     logger.info("=" * 80)
                #                     if should_exit_early:
                #                         return True, refined_code
                #                     else:
                #                         self.code = refined_code
                #                         logger.info("No testbench found - continuing to refine...")
                #                         continue
                #                 else:
                #                     logger.warning("Ports still incomplete, but accepting compilable code")
                #                     self.code = refined_code
                #                     logger.info("=" * 80)
                #                     logger.info(f"SUCCESS ON ITERATION {self.iteration}!")
                #                     logger.info("=" * 80)
                #                     if should_exit_early:
                #                         return True, refined_code
                #                     else:
                #                         logger.info("No testbench found - continuing to refine...")
                #                         continue
                #             else:
                #                 logger.warning("Port refinement broke compilation, reverting")
                #                 self.code_manager.write_code(target_file, self.code)
                #                 # Accept original compilable code
                #                 logger.info("=" * 80)
                #                 logger.info(f"SUCCESS ON ITERATION {self.iteration} (without port refinement)!")
                #                 logger.info("=" * 80)
                #                 if should_exit_early:
                #                     return True, self.code
                #                 else:
                #                     logger.info("No testbench found - continuing to refine...")
                #                     continue
                #         else:
                #             # Port refinement failed, accept compilable code
                #             logger.warning("Port refinement generation failed, accepting compilable code")
                #             logger.info("=" * 80)
                #             logger.info(f"SUCCESS ON ITERATION {self.iteration}!")
                #             logger.info("=" * 80)
                #             if should_exit_early:
                #                 return True, self.code
                #             else:
                #                 logger.info("No testbench found - continuing to refine...")
                #                 continue
                #     else:
                #         # All ports used!
                #         logger.info("=" * 80)
                #         logger.info(f"SUCCESS ON ITERATION {self.iteration}!")
                #         logger.info("=" * 80)
                #         if should_exit_early:
                #             return True, self.code
                #         else:
                #             logger.info("No testbench found - continuing to refine...")
                #             continue
                # else:
                # Port validation disabled
                logger.info("=" * 80)
                logger.info(f"SUCCESS ON ITERATION {self.iteration}!")
                logger.info("=" * 80)
                if should_exit_early:
                    return True, self.code
                else:
                    logger.info("No testbench found - continuing to refine...")
                    continue
            else:
                # Tests failed
                logger.warning("=" * 80)
                logger.warning(f"TESTS FAILED ON ITERATION {self.iteration}")
                logger.warning("=" * 80)
                logger.warning(f"Errors (first 500 chars):\n{self.errors[:500]}")
                
                # Small delay before next iteration
                time.sleep(2)
        
        # Max iterations reached
        logger.warning("=" * 80)
        logger.warning(f"MAX ITERATIONS ({self.max_iterations}) REACHED")
        logger.warning("=" * 80)
        logger.warning("Tests did not pass, but exiting cleanly")
        
        return False, self.code

#!/usr/bin/env python3
"""Build optimized prompts for SLM code generation"""

import logging
from typing import Dict, List
from prompts.templates import *

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Construct optimized prompts for SLM code generation"""
    
    def __init__(self, use_few_shot: bool = True, max_context_files: int = 10, slm_max_tokens: int = 8192):
        """
        Initialize prompt builder
        
        Args:
            use_few_shot: Whether to include few-shot examples
            max_context_files: Maximum number of context files to include
            slm_max_tokens: Maximum tokens available for SLM (from API config)
        """
        self.use_few_shot = use_few_shot
        self.max_context_files = max_context_files
        self.slm_max_tokens = slm_max_tokens
        
        # Simple token budget: Reserve 25% for output response, 75% for input prompt
        # Rough estimation: 1 token ~= 4 characters for English text
        input_tokens = int(slm_max_tokens * 0.75)  # 75% for input (system, task, examples, context)
        self.max_prompt_chars = input_tokens * 4    # Convert tokens to chars
        
        logger.info(f"Initialized PromptBuilder (few_shot={use_few_shot}, max_files={max_context_files})")
        logger.info(f"  SLM max tokens: {slm_max_tokens}")
        # logger.info(f"  Input budget: 75% = {input_tokens} tokens (~{self.max_prompt_chars} chars)")
        # logger.info(f"  Output reserve: 25% = {slm_max_tokens - input_tokens} tokens")
    
    # def build_initial_prompt(self, task: str, context: Dict[str, str]) -> str:
    #     """
    #     Build initial code generation prompt
        
    #     Args:
    #         task: Task description from prompt.json
    #         context: Dictionary of file_path -> content
            
    #     Returns:
    #         Formatted prompt string
    #     """
    #     # Format context files (prioritized)
    #     context_str = self._format_context(context)
        
    #     # Select relevant few-shot examples
    #     examples_str = ""
    #     if self.use_few_shot:
    #         examples_str = self._select_examples(task)
        
    #     prompt = INITIAL_GENERATION_TEMPLATE.format(
    #         system_prompt=SYSTEM_PROMPT,
    #         task_description=task,
    #         context_files=context_str,
    #         few_shot_examples=examples_str
    #     )
        
    #     logger.info(f"Built initial prompt: {len(prompt)} chars")
    #     return prompt
    
    def build_initial_prompt(self, task: str, context: Dict[str, str]) -> str:

        context_str = self.prompt_context(context)
        examples_str = ""
        if self.use_few_shot:
            examples_str = self._select_examples(task)
        
        # Get category description from environment file
        category_str = self._get_category_from_env()

        prompt = INITIAL_GENERATION_TEMPLATE.format(
            system_prompt=SYSTEM_PROMPT,
            category_description=category_str,
            task_description=task,
            context_files=context_str,
            few_shot_examples=examples_str
        )
        
        return prompt
    
    def _get_category_from_env(self) -> str:
        """
        Read the environment file from harness directory and extract category description
        
        Returns:
            Category description string from CATEGORY dict in templates.py
        """
        from pathlib import Path
        
        env_file_path = Path("/code/environment/env.txt")
        
        if not env_file_path.exists():
            logger.warning(f"Environment file not found: {env_file_path}")
            return ""
        
        try:
            with open(env_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("PROBLEM_CATEGORY="):
                        # Extract category value (e.g., "cid016")
                        category_value = line.split("=", 1)[1].strip()
                        
                        # Extract integer from category (e.g., "cid016" -> "16")
                        if category_value.startswith("cid"):
                            category_num = category_value[3:].lstrip('0') or '0'
                            
                            # Look up in CATEGORY dict
                            if category_num in CATEGORY:
                                logger.info(f"Found category {category_num} from {category_value}")
                                return CATEGORY[category_num]
                            else:
                                logger.warning(f"Category {category_num} not found in CATEGORY dict")
                                return ""
        except Exception as e:
            logger.error(f"Error reading environment file: {e}")
            return ""
        
        logger.warning("PROBLEM_CATEGORY not found in environment file")
        return ""

    def prompt_context(self, context: Dict[str, str]) -> str:

        lines = []
        file_count = 0
        total_context_chars = 0
        max_chars = self.max_prompt_chars

        priority_order = ["rtl/", "docs/", "verif/"]
        for prefix in priority_order:
            for file_path, content in context.items():
                if file_count >= self.max_context_files:
                    break
                if not file_path.startswith(prefix):
                    continue

                # Keep RTL files intact when possible, trim docs first, then verif.
                budget_left = max_chars - total_context_chars
                if budget_left <= 0:
                    break

                header = f"\n Consider the following content for the file: {file_path}\n```\n"
                footer = "\n```"
                overhead = len(header) + len(footer)
                if budget_left <= overhead:
                    break

                content_budget = budget_left - overhead
                file_content = content
                if len(file_content) > content_budget:
                    # Prefer preserving RTL context; docs/verif get truncated first.
                    if prefix in ("docs/", "verif/") or file_count > 0:
                        file_content = file_content[:content_budget] + "\n... (truncated)"
                    else:
                        file_content = file_content[:content_budget]

                file_section = f"{header}{file_content}{footer}"
                lines.append(file_section)
                total_context_chars += len(file_section)
                file_count += 1

            if file_count >= self.max_context_files or total_context_chars >= max_chars:
                break
        

        
        if not lines:
            return ""
        
        logger.info(f"Processed {file_count} context files")
        logger.info(f"Context budget usage: {total_context_chars}/{max_chars} chars")
        return "\n".join(lines)
    
    def build_refinement_prompt(
        self,
        task: str,
        context: Dict[str, str],
        previous_code: str,
        warnings: str,
        errors: str,
        # error_category: str,
        iteration: int,
        compilation: bool,
        test: bool
    ) -> str:
        """
        Build error-driven refinement prompt
        
        Args:
            task: Original task description
            previous_code: Code from previous iteration
            errors: Error messages from tests
            error_category: Category of errors (syntax, logic, etc.)
            iteration: Current iteration number
            
        Returns:
            Formatted refinement prompt
        """
        # Try to load test files for functional errors
        # test_context = self._get_test_context_if_available(errors, error_category)

        category_str = self._get_category_from_env()
        context_str = self.prompt_context(context)


        # prompt = INITIAL_GENERATION_TEMPLATE.format(
        #     system_prompt=SYSTEM_PROMPT,
        #     category_description=category_str,
        #     task_description=task,
        #     context_files=context_str,
        #     few_shot_examples=examples_str
        # )

        if not compilation:
            # compilation errors
            prompt = REFINEMENT_TEMPLATE_1.format(
                system_prompt=SYSTEM_PROMPT,
                category_description=category_str,
                task_description=task,
                context_files=context_str,
                previous_code=previous_code,
                error_messages=errors,
                iteration=iteration,
            )

        else:
            # testbench and warnings error
            if not warnings:
                prompt = REFINEMENT_TEMPLATE_2.format(
                    system_prompt=SYSTEM_PROMPT,
                    category_description=category_str,
                    task_description=task,
                    context_files=context_str,
                    previous_code=previous_code,
                    error_messages=errors,
                    iteration=iteration,
                )
            else:
                prompt = REFINEMENT_TEMPLATE_3.format(
                    system_prompt=SYSTEM_PROMPT,
                    category_description=category_str,
                    task_description=task,
                    context_files=context_str,
                    previous_code=previous_code,
                    error_messages=errors,
                    warning_messages=warnings,
                    iteration=iteration,
                )

            # prompt = REFINEMENT_TEMPLATE_2.format(
            #     system_prompt=SYSTEM_PROMPT_2,
            #     category_description=category_str,
            #     task_description=task,
            #     context_files=context_str,
            #     previous_code=previous_code,
            #     error_messages=errors,
            #     iteration=iteration,
            # )
        logger.info(f"Built refinement prompt: {len(prompt)} chars")
        return prompt
    
    def build_port_usage_prompt(
        self,
        current_code: str,
        unused_inputs: List[str],
        unused_outputs: List[str]
    ) -> str:
        """
        Build port usage refinement prompt (NEW)
        
        Args:
            current_code: Current code that compiles but has unused ports
            unused_inputs: List of unused input port names
            unused_outputs: List of unused output port names
            
        Returns:
            Formatted port usage prompt
        """
        unused_inputs_str = ", ".join(unused_inputs) if unused_inputs else "None"
        unused_outputs_str = ", ".join(unused_outputs) if unused_outputs else "None"
        
        prompt = PORT_USAGE_TEMPLATE.format(
            system_prompt=SYSTEM_PROMPT,
            current_code=current_code,
            unused_inputs=unused_inputs_str,
            unused_outputs=unused_outputs_str
        )
        
        logger.info(f"Built port usage prompt: {len(prompt)} chars")
        logger.info(f"  Unused inputs: {unused_inputs_str}")
        logger.info(f"  Unused outputs: {unused_outputs_str}")
        return prompt
    
    # def _format_context(self, context: Dict[str, str]) -> str:
    #     """
    #     Format context files with prioritization and dynamic budget allocation
        
    #     Args:
    #         context: Dictionary of file_path -> content
            
    #     Returns:
    #         Formatted context string
    #     """
    #     lines = []
    #     file_count = 0
    #     total_context_chars = 0
        
    #     # Calculate per-file budget: divide available chars by max files
    #     chars_per_file = self.max_prompt_chars // max(self.max_context_files, 1)
        
    #     # Priority order: rtl > docs > verif
    #     priority_order = ["rtl/", "docs/", "verif/"]
        
    #     for prefix in priority_order:
    #         for file_path, content in context.items():
    #             if file_path.startswith(prefix) and file_count < self.max_context_files:
    #                 # Truncate large files to per-file budget
    #                 truncated_content = content[:chars_per_file]
    #                 if len(content) > chars_per_file:
    #                     truncated_content += "\n... (truncated)"
                    
    #                 file_section = f"\nFILE: {file_path}\n```\n{truncated_content}\n```"
    #                 lines.append(file_section)
    #                 total_context_chars += len(file_section)
    #                 file_count += 1
        
    #     if not lines:
    #         return "No context files available"
        
    #     logger.info(f"Formatted {file_count} context files")
    #     logger.info(f"  Total context chars: {total_context_chars}")
    #     logger.info(f"  Per-file budget: {chars_per_file} chars")
    #     return "\n".join(lines)
    
    # def _format_context(self, context: Dict[str, str]) -> str:
    #     """
    #     Format context files with prioritization.
    #     RTL and verification files are kept fully, docs are truncated.

    #     Args:
    #         context: Dictionary of file_path -> content

    #     Returns:
    #         Formatted context string
    #     """
    #     lines = []
    #     file_count = 0
    #     total_context_chars = 0

    #     # Budget used only for docs files
    #     chars_per_file = self.max_prompt_chars // max(self.max_context_files, 1)

    #     # Priority order
    #     priority_order = ["rtl/", "docs/", "verif/"]

    #     for prefix in priority_order:
    #         for file_path, content in context.items():

    #             if not file_path.startswith(prefix):
    #                 continue

    #             if file_count >= self.max_context_files:
    #                 break

    #             # Default: full content
    #             file_content = content

    #             # Only truncate docs files
    #             if prefix == "docs/":
    #                 file_content = content[:chars_per_file]
    #                 if len(content) > chars_per_file:
    #                     file_content += "\n... (truncated)"

    #             file_section = f"\nFILE: {file_path}\n```\n{file_content}\n```"

    #             lines.append(file_section)
    #             total_context_chars += len(file_section)
    #             file_count += 1

    #     if not lines:
    #         return "No context files available"

    #     logger.info(f"Formatted {file_count} context files")

    #     return "\n".join(lines)
    
    def _select_examples(self, task: str) -> str:
        """
        Select relevant few-shot examples based on task keywords
        
        Args:
            task: Task description
            
        Returns:
            Formatted examples string
        """
        task_lower = task.lower()
        selected = []
        
        # Keyword matching for example selection
        if any(kw in task_lower for kw in ["counter", "count"]):
            selected.append(FEW_SHOT_EXAMPLES["counter"])
        
        if any(kw in task_lower for kw in ["fifo", "buffer", "queue"]):
            selected.append(FEW_SHOT_EXAMPLES["fifo"])
        
        if any(kw in task_lower for kw in ["fsm", "state", "machine"]):
            selected.append(FEW_SHOT_EXAMPLES["fsm"])
        
        # Default: include counter example if no specific match
        if not selected:
            selected.append(FEW_SHOT_EXAMPLES["counter"])
        
        logger.info(f"Selected {len(selected)} few-shot examples")
        return "\nDESIGN PATTERNS:\n" + "\n".join(selected)
    
    def _get_test_context_if_available(self, errors: str, error_category: str) -> str:
        """
        Load test file content if errors indicate functional test failures
        
        Args:
            errors: Error messages from test execution
            error_category: Category of error
            
        Returns:
            Formatted test context or empty string
        """
        from pathlib import Path
        
        # Check if this is a functional test failure (not compilation)
        if error_category in ["syntax", "undeclared", "type", "width"]:
            return ""  # Compilation errors don't need test code
        
        # Look for assertion errors or test failures
        if not any(kw in errors.lower() for kw in ["assert", "test case", "failed", "expected"]):
            return ""
        
        # Try to find test files in common locations
        test_paths = [
            Path("/code/verif"),
            Path("/code/src"),
            Path("/code/../src"),
        ]
        
        test_content = []
        for test_dir in test_paths:
            if not test_dir.exists():
                continue
                
            # Find test files (CocoTB or testbench)
            test_files = list(test_dir.glob("test_*.py")) + list(test_dir.glob("*_tb.sv")) + list(test_dir.glob("*_tb.v"))
            
            for test_file in test_files[:2]:  # Limit to 2 test files
                try:
                    content = test_file.read_text()
                    # Truncate if too long
                    if len(content) > 3000:
                        content = content[:3000] + "\n... (truncated)"
                    test_content.append(f"\nTEST FILE: {test_file.name}\n```python\n{content}\n```")
                except:
                    pass
        
        if test_content:
            logger.info(f"  Added {len(test_content)} test file(s) to refinement context")
            return "\n\nTEST CODE FOR REFERENCE:\n" + "\n".join(test_content)
        
        return ""

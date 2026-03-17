#!/usr/bin/env python3
"""Main agent coordinator"""

import logging
from typing import Optional
from config.settings import AgentConfig
from utils.logger import setup_logging
from llm.api_client import UnifiedAPIClient
from llm.response_parser import ResponseParser
from prompts.prompt_builder import PromptBuilder
from hdl.code_manager import CodeManager
from hdl.port_analyzer import PortAnalyzer
from testing.test_runner import TestRunner
from core.refinement_loop import RefinementLoop

logger = logging.getLogger(__name__)


class IterativeRefinementAgent:
    """Main agent that coordinates all components"""
    
    def __init__(self, config: Optional[AgentConfig] = None):
        """
        Initialize agent with configuration
        
        Args:
            config: Agent configuration (uses defaults if None)
        """
        # Use provided config or create default
        self.config = config or AgentConfig()
        
        # Setup logging
        setup_logging(self.config.log_file)
        
        logger.info("=" * 80)
        logger.info("INITIALIZING ITERATIVE REFINEMENT AGENT")
        logger.info("=" * 80)
        logger.info(f"Configuration:")
        logger.info(f"  Max iterations: {self.config.max_iterations}")
        logger.info(f"  API Type: {self.config.api_type}")
        if self.config.api_type == "openai":
            logger.info(f"  OpenAI Model: {self.config.slm_model}")
        else:
            logger.info(f"  SLM API URL: {self.config.slm_api_url}")
            logger.info(f"  SLM Model: {self.config.slm_model}")
        logger.info(f"  Port validation: {self.config.enable_port_validation}")
        logger.info(f"  Few-shot examples: {self.config.use_few_shot_examples}")
        
        # Initialize components
        self._initialize_components()
        
        logger.info("Agent initialized successfully")
    
    def _initialize_components(self):
        """Initialize all agent components"""
        # LLM interface - supports both SLM and OpenAI
        if self.config.api_type == "openai":
            self.llm_client = UnifiedAPIClient(
                api_type="openai",
                model=self.config.slm_model,
                max_length=self.config.slm_max_length,
                timeout=self.config.slm_timeout,
                openai_api_key=self.config.openai_api_key
            )
        else:
            self.llm_client = UnifiedAPIClient(
                api_type="slm",
                model=self.config.slm_model,
                max_length=self.config.slm_max_length,
                timeout=self.config.slm_timeout,
                api_url=self.config.slm_api_url
            )
        
        self.response_parser = ResponseParser()
        
        # Prompt engineering
        self.prompt_builder = PromptBuilder(
            use_few_shot=self.config.use_few_shot_examples,
            max_context_files=self.config.max_context_files,
            slm_max_tokens=self.config.slm_max_length
        )
        
        # HDL operations
        self.code_manager = CodeManager()
        self.port_analyzer = PortAnalyzer()
        
        # Testing
        self.test_runner = TestRunner(
            test_timeout=self.config.test_timeout,
            lint_timeout=self.config.lint_timeout
        )
        
        # Refinement loop
        self.refinement_loop = RefinementLoop(
            llm_client=self.llm_client,
            prompt_builder=self.prompt_builder,
            code_manager=self.code_manager,
            response_parser=self.response_parser,
            port_analyzer=self.port_analyzer,
            test_runner=self.test_runner,
            max_iterations=self.config.max_iterations,
            enable_port_validation=self.config.enable_port_validation
        )
    
    def run(self) -> int:
        """
        Main agent execution
        
        Returns:
            Exit code (0 for success)
        """
        try:
            logger.info("=" * 80)
            logger.info("STARTING AGENT EXECUTION")
            logger.info("=" * 80)
            
            # Step 1: Read task
            logger.info("\nStep 1: Reading task...")
            task = self.code_manager.read_prompt()
            if not task:
                logger.error("No task found in prompt.json")
                return 0  # Exit cleanly even on error
            
            # Step 2: Gather context
            logger.info("\nStep 2: Gathering context...")
            context = self.code_manager.gather_context()
            
            # Step 3: Find target file
            logger.info("\nStep 3: Finding target file...")
            temp_target_file = self.code_manager.find_temp_target_file()
            if not temp_target_file:
                logger.error("Could not determine target file")
                return 0
            
            logger.info(f"Target file: {temp_target_file}")
            
            # Step 4: Run refinement loop
            logger.info("\nStep 4: Starting refinement loop...")
            success, final_code = self.refinement_loop.run(task, context, temp_target_file)
            
            # Final status
            if success:
                logger.info("\n" + "=" * 80)
                logger.info("AGENT COMPLETED SUCCESSFULLY")
                logger.info("=" * 80)
                logger.info(f"Final code written to: {temp_target_file}")
            else:
                logger.warning("\n" + "=" * 80)
                logger.warning("AGENT COMPLETED WITH WARNINGS")
                logger.warning("=" * 80)
                logger.warning("Code generated but tests did not pass")
                if final_code:
                    logger.info(f"Best attempt written to: {temp_target_file}")
            
            # Always return 0 for benchmark compatibility
            return 0
            
        except Exception as e:
            logger.error(f"\nAgent failed with exception: {e}", exc_info=True)
            return 0  # Exit cleanly even on error

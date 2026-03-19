#!/usr/bin/env python3
"""Centralized configuration management"""

import os
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


def count_files_in_directories(base_dirs: list) -> int:
    """
    Count total number of files in specified directories
    
    Args:
        base_dirs: List of directory paths to count files in
        
    Returns:
        Total count of files across all directories
    """
    total_count = 0
    for dir_path in base_dirs:
        path = Path(dir_path)
        if path.exists() and path.is_dir():
            # Count all files (not directories) recursively
            file_count = sum(1 for item in path.rglob('*') if item.is_file())
            total_count += file_count
    return max(total_count, 1)  # Ensure at least 1 to avoid division by zero


@dataclass
class AgentConfig:
    """Configuration for SLM Agent with validation"""
    
    # Iteration settings
    max_iterations: int = 3
    early_exit_on_success: bool = True
    
    # API settings - supports both local SLM and OpenAI
    api_type: str = field(default_factory=lambda: os.getenv("API_TYPE", "slm"))  # "slm" or "openai"
    slm_api_url: str = field(default_factory=lambda: os.getenv("SLM_API_URL", "http://host.docker.internal:8001"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    slm_model: str = field(default_factory=lambda: os.getenv("SLM_MODEL", "granite"))
    slm_max_length: int = field(default_factory=lambda: int(os.getenv("SLM_MAX_LENGTH", "12288")))
    slm_timeout: int = field(default_factory=lambda: int(os.getenv("SLM_TIMEOUT", "300")))
    slm_temperature: float = field(default_factory=lambda: float(os.getenv("SLM_TEMPERATURE", "0.15")))
    slm_top_p: float = field(default_factory=lambda: float(os.getenv("SLM_TOP_P", "0.95")))
    
    # Prompt engineering settings
    use_few_shot_examples: bool = False
    max_context_files: int = field(default_factory=lambda: count_files_in_directories([
        "/code/rtl",
        "/code/docs", 
        "/code/verif"
    ]))
    enable_port_validation: bool = False
    
    # Testing settings
    test_timeout: int = 180
    lint_timeout: int = 30
    
    # Logging
    log_file: str = '/code/rundir/agent_detailed.log'
    
    def validate(self) -> None:
        """Validate configuration values"""
        assert self.max_iterations > 0, "max_iterations must be positive"
        assert self.slm_timeout > 0, "slm_timeout must be positive"
        assert self.slm_max_length >= 1024, "slm_max_length too small (min: 1024)"
        assert 0.0 <= self.slm_temperature <= 2.0, "slm_temperature must be in [0.0, 2.0]"
        assert 0.0 < self.slm_top_p <= 1.0, "slm_top_p must be in (0.0, 1.0]"
        assert self.test_timeout > 0, "test_timeout must be positive"
        assert self.lint_timeout > 0, "lint_timeout must be positive"
        assert self.api_type in ["slm", "openai"], "api_type must be 'slm' or 'openai'"
        
        if self.api_type == "openai":
            assert self.openai_api_key.strip(), "OPENAI_API_KEY must be set for OpenAI API type"
        # assert self.max_context_files > 0, "max_context_files must be positive"
    
    def __post_init__(self):
        """Validate on initialization"""
        self.validate()

#!/usr/bin/env python3
"""Manage Verilog code files and context gathering"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class CodeManager:
    """Manage HDL code files and context"""
    
    def __init__(self):
        """Initialize CodeManager and load environment variables"""
        # Load environment variables from /code/src/.env if it exists
        env_file = Path("/code/src/.env")
        if env_file.exists():
            load_dotenv(env_file)
            logger.info(f"Loaded environment variables from {env_file}")
        else:
            logger.warning(f"Environment file not found: {env_file}")

    def _get_verilog_sources(self) -> list[str]:
        """Return VERILOG_SOURCES entries from environment."""
        raw_sources = (os.getenv("VERILOG_SOURCES") or "").strip()
        if not raw_sources:
            return []
        return [entry.strip() for entry in raw_sources.split() if entry.strip()]

    @staticmethod
    def _get_string_similarity(s1: str, s2: str) -> float:
        """Compute a simple positional character similarity score in [0, 1]."""
        s1_lower = s1.lower()
        s2_lower = s2.lower()

        max_len = max(len(s1_lower), len(s2_lower))
        if max_len == 0:
            return 1.0

        matches = sum(1 for a, b in zip(s1_lower, s2_lower) if a == b)
        return matches / max_len

    def _get_filename_from_verilog_sources(self) -> Optional[str]:
        """
        Determine target filename from VERILOG_SOURCES.

        Supports direct file paths like /code/rtl/GP.v and wildcard patterns like
        /code/rtl/*.sv (combined with TOPLEVEL).
        """
        sources = self._get_verilog_sources()
        if not sources:
            return None

        toplevel = os.getenv("TOPLEVEL")

        explicit_source_names: list[str] = []
        wildcard_suffixes: list[str] = []

        for source in sources:
            source_name = Path(source).name
            if not source_name:
                continue

            # Track wildcard entries (e.g. *.sv) for fallback handling.
            if "*" in source_name:
                source_suffix = Path(source_name).suffix
                if source_suffix:
                    wildcard_suffixes.append(source_suffix)
                continue

            explicit_source_names.append(source_name)

        if len(explicit_source_names) == 1:
            return explicit_source_names[0]

        if len(explicit_source_names) > 1:
            if toplevel:
                best_name = max(
                    explicit_source_names,
                    key=lambda name: self._get_string_similarity(Path(name).stem, toplevel),
                )
                logger.info(
                    "Multiple VERILOG_SOURCES entries found; "
                    f"selected best match '{best_name}' for TOPLEVEL '{toplevel}'"
                )
                return best_name

            logger.info(
                "Multiple VERILOG_SOURCES entries found and TOPLEVEL is unset; "
                f"using first entry '{explicit_source_names[0]}'"
            )
            return explicit_source_names[0]

        if wildcard_suffixes and toplevel:
            return f"{toplevel}{wildcard_suffixes[0]}"

        return None
    
    def get_expected_filename(self) -> str:
        """
        Get expected target filename based on VERILOG_SOURCES first, then TOPLEVEL.
        
        Returns:
            Expected filename
        """
        source_filename = self._get_filename_from_verilog_sources()
        if source_filename:
            logger.info(f"Expected filename from VERILOG_SOURCES: {source_filename}")
            return source_filename

        # Fallback to TOPLEVEL-based naming when VERILOG_SOURCES is unavailable.
        toplevel = os.getenv("TOPLEVEL")
        if toplevel:
            expected_filename = f"{toplevel}.sv"
            logger.info(f"Expected filename from TOPLEVEL: {expected_filename}")
            return expected_filename

        logger.warning("VERILOG_SOURCES/TOPLEVEL not set, using default 'top.sv'")
        return "top.sv"
    
    def read_prompt(self, prompt_file: str = "/code/prompt.json") -> str:
        """
        Read task from prompt.json
        
        Args:
            prompt_file: Path to prompt JSON file
            
        Returns:
            Task description string
        """
        try:
            with open(prompt_file, "r") as f:
                data = json.load(f)
                prompt = data.get("prompt", "")
                logger.info(f"Read task from {prompt_file}")
                logger.info(f"   Task preview: {prompt[:150]}...")
                return prompt
        except FileNotFoundError:
            logger.error(f"Prompt file not found: {prompt_file}")
            return ""
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in prompt file: {e}")
            return ""
        except Exception as e:
            logger.error(f"Error reading prompt: {e}")
            return ""
    
    def gather_context(self, base_dir: str = "/code") -> Dict[str, str]:
        """
        Gather all existing files as context
        
        Args:
            base_dir: Base directory to search
            
        Returns:
            Dictionary mapping file_path -> content
        """
        context = {}
        
        # Directories to search
        search_dirs = ["docs", "rtl", "verif", "rundir"]
        
        for dir_name in search_dirs:
            dir_path = Path(base_dir) / dir_name
            
            if not dir_path.exists():
                logger.info(f"   Directory not found: {dir_name}/")
                continue
            
            # Recursively find all files
            for file_path in dir_path.rglob("*"):
                if file_path.is_file():
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            relative_path = file_path.relative_to(base_dir)
                            content = f.read()
                            context[str(relative_path)] = content
                            logger.info(f"   Loaded: {relative_path} ({len(content)} bytes)")
                    except Exception as e:
                        logger.warning(f"   Could not read {file_path}: {e}")
        
        logger.info(f"Gathered context from {len(context)} files")
        return context
    
    def find_temp_target_file(self, rtl_dir: str = "/code/rtl") -> Optional[Path]:
        """
        Find the file that needs to be created/modified
        
        Args:
            rtl_dir: RTL directory path
            
        Returns:
            Path to target file or None
        """
        rtl_path = Path(rtl_dir)
        
        # Check if RTL directory exists
        if not rtl_path.exists():
            logger.warning(f"RTL directory not found: {rtl_dir}")
            rtl_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"   Created RTL directory: {rtl_dir}")
        
        # Strategy 1: Find empty files
        for file_path in rtl_path.iterdir():
            if file_path.is_file() and file_path.stat().st_size == 0:
                logger.info(f"Found empty target file: {file_path}")
                return file_path
        
        # Strategy 2: Use expected filename based on TOPLEVEL environment variable
        expected_filename = self.get_expected_filename()
        expected_path = rtl_path / expected_filename
        
        if not expected_path.exists():
            logger.info(f"Will create target file based on TOPLEVEL: {expected_path}")
            return expected_path
        else:
            logger.info(f"Using existing file based on TOPLEVEL: {expected_path}")
            return expected_path
    
    def write_code(self, file_path: Path, code: str) -> bool:
        """
        Write code to file
        
        Args:
            file_path: Target file path
            code: Code content to write
            
        Returns:
            True if successful
        """
        try:
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write code
            with open(file_path, "w") as f:
                f.write(code)
            
            logger.info(f"Wrote {len(code)} bytes to {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error writing to {file_path}: {e}")
            return False
    
    def backup_code(self, file_path: Path) -> bool:
        """
        Create backup of existing file
        
        Args:
            file_path: File to backup
            
        Returns:
            True if successful
        """
        try:
            if not file_path.exists():
                return True
            
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            content = file_path.read_text()
            backup_path.write_text(content)
            
            logger.info(f"Created backup: {backup_path}")
            return True
            
        except Exception as e:
            logger.warning(f"Could not create backup: {e}")
            return False


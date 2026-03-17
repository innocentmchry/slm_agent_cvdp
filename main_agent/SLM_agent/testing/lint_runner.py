#!/usr/bin/env python3
"""Run Verilator and Icarus Verilog lint checks"""

import subprocess
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class LintRunner:
    """Run HDL lint checks using Verilator or Icarus Verilog"""
    
    def __init__(self, timeout: int = 30):
        """
        Initialize lint runner
        
        Args:
            timeout: Timeout for lint commands in seconds
        """
        self.timeout = timeout
    
    def run(self, rtl_code: str) -> Tuple[bool, str]:
        """
        Run lint checks on RTL code string
        
        Args:
            rtl_code: RTL code as string
            
        Returns:
            Tuple of (success, error_messages)
        """
        if not rtl_code or not rtl_code.strip():
            logger.warning("No RTL code to lint")
            return False, "No RTL code provided"
        
        logger.info(f"Linting RTL code: {len(rtl_code)} bytes...")
        
        # Try Verilator first
        success, errors = self._run_verilator(rtl_code)
        if success or errors:  # If verilator worked (even with errors)
            return success, errors
        
        # Fallback to Icarus Verilog
        logger.info("Verilator not available, trying Icarus Verilog...")
        return self._run_icarus(rtl_code)
    
    def _run_verilator(self, rtl_code: str) -> Tuple[bool, str]:
        """Run Verilator lint checks on RTL code string"""
        try:
            # Create temporary file for RTL code
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.v', delete=False) as f:
                f.write(rtl_code)
                temp_file = f.name
            
            try:
                # Run without -Wall to only check for compilation errors, not style warnings
                cmd = ["verilator", "--lint-only", temp_file]
                
                logger.info(f"Running: {' '.join(cmd)}")
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout
                )
                
                output = result.stderr + result.stdout
                
                # Check if there are actual syntax/compilation errors (not just warnings)
                # Verilator outputs "%Error: syntax error" for real errors
                # But "%Error: Exiting due to N warning(s)" is just a summary of warnings
                # We only want to fail on actual compilation errors, not warnings
                has_real_errors = False
                
                for line in output.split('\n'):
                    if '%Error:' in line:
                        # Check if it's a real error or just the warnings summary
                        if 'Exiting due to' not in line and 'warning(s)' not in line.lower():
                            # Check if it's an actual compilation error (not a warning)
                            # Real errors have messages like "syntax error", "not declared", etc.
                            # Warnings have error codes like "%Error-ASSIGNIN", "%Error-WIDTH", etc.
                            if '%Error-' not in line:
                                # No error code means it's a real compilation error
                                has_real_errors = True
                                break
                
                if result.returncode == 0:
                    logger.info("Verilator lint checks PASSED")
                    return True, ""
                elif not has_real_errors:
                    # Only warnings (with error codes like %Error-XXX), no real compilation errors
                    logger.info("Verilator has warnings but no compilation errors - treating as PASSED")
                    logger.info(f"Warnings: {output[:500]}")  # Log first 500 chars of warnings
                    return True, {output[:500]}
                else:
                    logger.warning("Verilator lint checks FAILED with compilation errors")
                    # Extract first 50 lines of errors
                    error_lines = output.split("\n")[:50]
                    errors = "\n".join(error_lines)
                    return False, errors
            
            finally:
                # Clean up temporary file
                import os
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    
        except FileNotFoundError:
            logger.info("Verilator not found")
            return False, ""
        except subprocess.TimeoutExpired:
            logger.error(f"Verilator timeout after {self.timeout}s")
            return False, f"Lint timeout after {self.timeout}s"
        except Exception as e:
            logger.warning(f"Verilator error: {e}")
            return False, ""
    
    def _run_icarus(self, rtl_code: str) -> Tuple[bool, str]:
        """Run Icarus Verilog lint checks on RTL code string"""
        try:
            # Create temporary file for RTL code
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.v', delete=False) as f:
                f.write(rtl_code)
                temp_file = f.name
            
            try:
                # Run without -Wall to only check for compilation errors
                cmd = ["iverilog", "-tnull", temp_file]
                
                logger.info(f"Running: {' '.join(cmd)}")
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout
                )
                
                output = result.stderr + result.stdout
                
                # Check for actual errors (not just warnings)
                has_errors = "error:" in output.lower() and result.returncode != 0
                
                if result.returncode == 0:
                    logger.info("Icarus Verilog checks PASSED")
                    return True, ""
                elif not has_errors:
                    # Only warnings, treat as success
                    logger.info("Icarus Verilog has warnings but compiles - treating as PASSED")
                    logger.info(f"Warnings: {output[:500]}")
                    return True, ""
                else:
                    logger.warning("Icarus Verilog checks FAILED with compilation errors")
                    error_lines = output.split("\n")[:50]
                    errors = "\n".join(error_lines)
                    return False, errors
            
            finally:
                # Clean up temporary file
                import os
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    
        except FileNotFoundError:
            logger.error("Icarus Verilog not found")
            return False, "No suitable lint tool available (tried Verilator and Icarus)"
        except subprocess.TimeoutExpired:
            logger.error(f"Icarus timeout after {self.timeout}s")
            return False, f"Lint timeout after {self.timeout}s"
        except Exception as e:
            logger.error(f"Icarus error: {e}")
            return False, str(e)

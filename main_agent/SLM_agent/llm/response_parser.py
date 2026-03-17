#!/usr/bin/env python3
"""Parse and extract Verilog code from SLM responses"""

import re
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ResponseParser:
    """Extract and validate Verilog code from SLM responses"""
    
    @staticmethod
    def _remove_reasoning_text(response: str) -> str:
        """
        Remove common LLM reasoning patterns before extraction
        
        Args:
            response: Raw response that may contain reasoning text
            
        Returns:
            Response with reasoning text removed
        """
        # Only remove leading text that's clearly reasoning/explanation before code blocks
        # Look for patterns like "Let me...", "Here's...", "Okay" that come before markdown blocks
        # But preserve the markdown and code structure itself
        
        # If the response contains markdown code blocks, try to clean up text before them
        if '```' in response:
            # Find the position of the first markdown block
            first_block = response.find('```')
            if first_block > 0:
                # Only remove text before the first ``` if it's mostly non-code text
                pre_block = response[:first_block].strip()
                # If the pre-block text is short (explanatory text), remove it
                if len(pre_block) < 500 and len(pre_block.split('\n')) < 10:
                    response = response[first_block:]
        
        return response
    
    @staticmethod
    def extract_verilog(response: str) -> str:
        """
        Extract Verilog code from various response formats
        
        Tries multiple strategies:
        1. Markdown code blocks (```verilog, ```systemverilog, ```sv) - extracts ALL modules
        2. Module boundaries (module...endmodule) with proper syntax - extracts ALL modules
        3. Raw response (if no markers found)
        
        Args:
            response: Raw response from SLM
            
        Returns:
            Extracted Verilog code (combined if multiple modules found)
        """
        if not response:
            logger.warning("Empty response received")
            return ""
        
        # Pre-process to remove reasoning text
        response = ResponseParser._remove_reasoning_text(response)
        
        # Strategy 1: Markdown code blocks - fixed pattern to capture all modules before closing backticks
        markdown_patterns = [
            r'```(?:verilog|systemverilog|sv)\s*\n(.*?)\n?```',
            r'```\s*\n(.*?)\n?```',
        ]
        
        for pattern in markdown_patterns:
            match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
            if match:
                code = match.group(1).strip()
                # Count modules in the extracted code
                modules_found = re.findall(r'module\s+(\w+)', code, re.IGNORECASE)
                logger.info(f"Extracted from markdown block: {len(code)} bytes, {len(modules_found)} module(s): {modules_found}")
                return code
        
        # Strategy 2: Module boundaries - extract ALL modules with proper module declaration syntax
        if 'module ' in response.lower():
            # Match all proper module declarations: module <name> followed by ( or #
            # This prevents matching "the module" or "module has to" in reasoning text
            # Use non-greedy matching to capture each module block separately
            matches = re.findall(
                r'module\s+\w+\s*[\(#].*?endmodule',
                response,
                re.DOTALL | re.IGNORECASE
            )
            if matches:
                # Combine all extracted modules with newlines between them
                code = '\n\n'.join(match.strip() for match in matches)
                logger.info(f"Extracted {len(matches)} module(s): {len(code)} bytes total")
                return code
        
        # Strategy 3: Use raw response
        logger.info(f"Using raw response: {len(response)} bytes")
        return response.strip()
    
    @staticmethod
    def extract_module_name(code: str) -> Optional[str]:
        """
        Extract module name from Verilog code
        
        Args:
            code: Verilog source code
            
        Returns:
            Module name or None if not found
        """
        match = re.search(r'module\s+(\w+)', code, re.IGNORECASE)
        if match:
            module_name = match.group(1)
            logger.info(f"Module name: {module_name}")
            return module_name
        else:
            logger.warning("No module name found in code")
            return None
    
    @staticmethod
    def validate_basic_structure(code: str) -> bool:
        """
        Perform basic validation of Verilog structure
        
        Args:
            code: Verilog source code
            
        Returns:
            True if basic structure is valid
        """
        if not code:
            logger.warning("Empty code provided for validation")
            return False
        
        # Check for module keyword
        if 'module' not in code.lower():
            logger.warning("No 'module' keyword found")
            return False
        
        # Check for endmodule keyword
        if 'endmodule' not in code.lower():
            logger.warning("No 'endmodule' keyword found")
            return False
        
        # Check balanced parentheses
        open_parens = code.count('(')
        close_parens = code.count(')')
        if open_parens != close_parens:
            logger.warning(f"Unbalanced parentheses: {open_parens} open, {close_parens} close")
            return False
        
        logger.info("Basic structure validation passed")
        return True
    
    @staticmethod
    def _get_string_similarity(s1: str, s2: str) -> float:
        """
        Calculate similarity between two strings using character matching
        
        Args:
            s1: First string
            s2: Second string
            
        Returns:
            Similarity score (0.0 to 1.0)
        """
        s1_lower = s1.lower()
        s2_lower = s2.lower()
        
        # Count matching characters in same positions
        matches = sum(1 for a, b in zip(s1_lower, s2_lower) if a == b)
        max_len = max(len(s1_lower), len(s2_lower))
        
        if max_len == 0:
            return 1.0
        
        return matches / max_len
    
    @staticmethod
    def validate_module_name(code: str) -> str:
        """
        Validate and correct module name to match TOPLEVEL environment variable
        
        For code with multiple modules:
        1. Check if TOPLEVEL already exists - if yes, keep all modules unchanged
        2. Find the module name CLOSEST to TOPLEVEL (using character matching)
        3. Rename only that module to match TOPLEVEL
        4. Keep all other modules unchanged (they may be dependencies)
        
        Args:
            code: Verilog source code
            
        Returns:
            Code with corrected module name if needed
        """
        toplevel = os.getenv("TOPLEVEL")
        
        if not toplevel:
            logger.warning("TOPLEVEL environment variable not set, skipping module name validation")
            return code
        
        # Find all module names in the code
        module_names = re.findall(r'\bmodule\s+(\w+)', code, re.IGNORECASE)
        
        if not module_names:
            logger.warning("No module declaration found in code")
            return code
        
        logger.info(f"Found modules: {module_names}")
        
        # Check if TOPLEVEL already exists in the code
        if toplevel in module_names:
            logger.info(f"Module '{toplevel}' already present in code - keeping all modules unchanged")
            logger.debug(f"Code has {len(module_names)} total module(s)")
            return code
        
        # Find the module name closest to TOPLEVEL
        best_match = None
        best_similarity = -1
        
        for module_name in module_names:
            similarity = ResponseParser._get_string_similarity(module_name, toplevel)
            logger.debug(f"Similarity between '{module_name}' and '{toplevel}': {similarity:.2f}")
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = module_name
        
        if best_match is None:
            logger.warning("Could not find a suitable module to rename")
            return code
        
        logger.info(f"Closest match to TOPLEVEL '{toplevel}': '{best_match}' (similarity: {best_similarity:.2f})")
        
        if best_match == toplevel:
            logger.info(f"Module '{best_match}' matches TOPLEVEL")
            return code
        
        # Rename the best matching module to TOPLEVEL
        logger.warning(f"Renaming module '{best_match}' to '{toplevel}'")
        
        # Replace only the first occurrence of best_match module declaration
        # Use word boundary to avoid partial matches
        pattern = r'(module\s+)' + re.escape(best_match) + r'(\s*[\(#])'
        updated_code = re.sub(
            pattern,
            r'\1' + toplevel + r'\2',
            code,
            count=1,
            flags=re.IGNORECASE
        )
        
        logger.info(f"Module name '{best_match}' updated to '{toplevel}'")
        module_count = len(re.findall(r'\bmodule\s+(\w+)', updated_code, re.IGNORECASE))
        logger.debug(f"Result contains {module_count} module(s)")
        return updated_code
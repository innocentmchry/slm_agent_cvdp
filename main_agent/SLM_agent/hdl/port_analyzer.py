#!/usr/bin/env python3
"""Analyze Verilog module for port usage completeness (NEW FEATURE)"""

import re
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class PortAnalyzer:
    """Analyze Verilog module for port usage completeness"""
    
    def analyze(self, code: str) -> Dict:
        """
        Main analysis entry point - validates all ports are used
        
        Args:
            code: Verilog/SystemVerilog source code
            
        Returns:
            Dictionary with analysis results:
            {
                "all_ports_used": bool,
                "unused_inputs": List[str],
                "unused_outputs": List[str],
                "port_usage": Dict[str, str],
                "feedback": str
            }
        """
        logger.info("Starting port usage analysis...")
        
        # Extract module interface
        inputs = self._extract_inputs(code)
        outputs = self._extract_outputs(code)
        
        logger.info(f"  Found {len(inputs)} input ports, {len(outputs)} output ports")
        
        if not inputs and not outputs:
            logger.warning("  No ports found in code")
            return {
                "all_ports_used": True,
                "unused_inputs": [],
                "unused_outputs": [],
                "port_usage": {},
                "feedback": "No ports found in module"
            }
        
        # Extract module body (exclude interface)
        body = self._extract_module_body(code)
        
        # Analyze usage
        unused_inputs = []
        unused_outputs = []
        port_usage = {}
        
        for inp in inputs:
            if self._is_port_used(inp, body):
                port_usage[inp] = "used"
            else:
                unused_inputs.append(inp)
                port_usage[inp] = "UNUSED"
        
        for out in outputs:
            if self._is_port_assigned(out, body):
                port_usage[out] = "assigned"
            else:
                unused_outputs.append(out)
                port_usage[out] = "UNASSIGNED"
        
        # Generate feedback
        all_used = len(unused_inputs) == 0 and len(unused_outputs) == 0
        feedback = self._generate_feedback(unused_inputs, unused_outputs)
        
        if all_used:
            logger.info("  All ports properly used!")
        else:
            logger.warning("  Some ports are not used!")
            if unused_inputs:
                logger.warning(f"    Unused inputs: {unused_inputs}")
            if unused_outputs:
                logger.warning(f"    Unassigned outputs: {unused_outputs}")
        
        return {
            "all_ports_used": all_used,
            "unused_inputs": unused_inputs,
            "unused_outputs": unused_outputs,
            "port_usage": port_usage,
            "feedback": feedback
        }
    
    def _extract_inputs(self, code: str) -> List[str]:
        """Extract input port names from module"""
        inputs = []
        
        # Pattern: input [logic/wire/reg] [width] name [, name]
        patterns = [
            r'input\s+(?:logic|wire|reg)?\s*(?:\[[^\]]+\])?\s+(\w+)',
            r'input\s+(\w+)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, code, re.MULTILINE)
            inputs.extend(matches)
        
        # Remove duplicates and filter out keywords
        keywords = {'input', 'output', 'logic', 'wire', 'reg', 'signed', 'unsigned'}
        inputs = [inp for inp in set(inputs) if inp not in keywords]
        
        return sorted(inputs)
    
    def _extract_outputs(self, code: str) -> List[str]:
        """Extract output port names from module"""
        outputs = []
        
        patterns = [
            r'output\s+(?:logic|wire|reg)?\s*(?:\[[^\]]+\])?\s+(\w+)',
            r'output\s+(\w+)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, code, re.MULTILINE)
            outputs.extend(matches)
        
        # Remove duplicates and filter out keywords
        keywords = {'input', 'output', 'logic', 'wire', 'reg', 'signed', 'unsigned'}
        outputs = [out for out in set(outputs) if out not in keywords]
        
        return sorted(outputs)
    
    def _extract_module_body(self, code: str) -> str:
        """
        Extract module body (logic after port declarations)
        
        Args:
            code: Full module code
            
        Returns:
            Module body without interface
        """
        # Find the end of port list (after closing parenthesis and semicolon)
        match = re.search(r'\);', code)
        if match:
            return code[match.end():]
        
        # Fallback: return everything after first semicolon
        match = re.search(r';', code)
        if match:
            return code[match.end():]
        
        return code
    
    def _is_port_used(self, port_name: str, body: str) -> bool:
        """
        Check if input port is referenced in module body
        
        Args:
            port_name: Name of input port
            body: Module body text
            
        Returns:
            True if port is used
        """
        # Look for port name used in expressions (word boundary)
        pattern = r'\b' + re.escape(port_name) + r'\b'
        return bool(re.search(pattern, body))
    
    def _is_port_assigned(self, port_name: str, body: str) -> bool:
        """
        Check if output port is assigned in module body
        
        Args:
            port_name: Name of output port
            body: Module body text
            
        Returns:
            True if port has assignment
        """
        # Look for assignments to port
        patterns = [
            r'\b' + re.escape(port_name) + r'\s*<=',   # Non-blocking
            r'\b' + re.escape(port_name) + r'\s*=',    # Blocking
            r'assign\s+' + re.escape(port_name),       # Continuous assignment
        ]
        
        for pattern in patterns:
            if re.search(pattern, body):
                return True
        
        return False
    
    def _generate_feedback(
        self,
        unused_inputs: List[str],
        unused_outputs: List[str]
    ) -> str:
        """
        Generate human-readable feedback for unused ports
        
        Args:
            unused_inputs: List of unused input port names
            unused_outputs: List of unassigned output port names
            
        Returns:
            Formatted feedback string
        """
        if not unused_inputs and not unused_outputs:
            return "All ports are properly used and assigned."
        
        feedback_parts = []
        
        if unused_inputs:
            feedback_parts.append(
                f"UNUSED INPUT PORTS: {', '.join(unused_inputs)}\n"
                f"   These input ports are declared but never referenced in the module logic.\n"
                f"   Recommendation: Use these inputs in conditional logic, state machines, or computations."
            )
        
        if unused_outputs:
            feedback_parts.append(
                f"UNASSIGNED OUTPUT PORTS: {', '.join(unused_outputs)}\n"
                f"   These output ports are declared but never assigned any value.\n"
                f"   Recommendation: Add assignments (blocking, non-blocking, or continuous) for these outputs."
            )
        
        return "\n\n".join(feedback_parts)

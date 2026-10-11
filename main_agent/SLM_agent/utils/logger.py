#!/usr/bin/env python3
"""Logging utilities with dual output support"""

import sys
import logging
from typing import Optional


class TeeLogger:
    """Logger that writes to both stdout and file simultaneously"""
    
    def __init__(self, filename: str):
        self.terminal = sys.stdout
        self.log = open(filename, 'a', buffering=1)  # Line buffered
    
    def write(self, message: str):
        self.terminal.write(message)
        self.terminal.flush()
        self.log.write(message)
        self.log.flush()
    
    def flush(self):
        self.terminal.flush()
        self.log.flush()


def setup_logging(log_file: str = '/code/rundir/agent_detailed.log') -> logging.Logger:
    """
    Configure logging with dual output (stdout + file)
    
    Args:
        log_file: Path to log file
        
    Returns:
        Configured logger instance
    """
    tee = TeeLogger(log_file)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=tee,
        force=True
    )
    
    # Redirect stdout to tee for print statements
    sys.stdout = tee
    
    return logging.getLogger(__name__)

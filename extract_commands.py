#!/usr/bin/env python3
"""
Script to extract all 'command' fields from docker-compose.yml files
in the cvdp_copilot_* directories under gpt-4o-mini_1
"""

import os
import yaml
from pathlib import Path
from collections import defaultdict

def extract_commands(base_path):
    """
    Extract commands from docker-compose.yml files.
    
    Args:
        base_path: Path to /home/innocent/my_agentic_ai/cvdp_benchmark/gpt-4o-mini_1
    
    Returns:
        Dictionary mapping project names to list of (harness_number, command) tuples
    """
    base_path = Path(base_path)
    commands_by_project = defaultdict(list)
    
    # Iterate through all cvdp_copilot_* directories
    for project_dir in sorted(base_path.glob("cvdp_copilot_*")):
        if not project_dir.is_dir():
            continue
        
        project_name = project_dir.name
        harness_dir = project_dir / "harness"
        
        if not harness_dir.exists():
            continue
        
        # Iterate through integer folders in harness directory
        for harness_num_dir in sorted(harness_dir.iterdir()):
            if not harness_num_dir.is_dir():
                continue
            
            # Check if folder name is an integer
            try:
                harness_num = int(harness_num_dir.name)
            except ValueError:
                continue
            
            docker_compose_file = harness_num_dir / "docker-compose.yml"
            
            if docker_compose_file.exists():
                try:
                    with open(docker_compose_file, 'r') as f:
                        docker_config = yaml.safe_load(f)
                    
                    # Extract command from services
                    if docker_config and 'services' in docker_config:
                        for service_name, service_config in docker_config['services'].items():
                            if 'command' in service_config:
                                command = service_config['command']
                                commands_by_project[project_name].append({
                                    'harness': harness_num,
                                    'service': service_name,
                                    'command': command
                                })
                except yaml.YAMLError as e:
                    print(f"Error parsing {docker_compose_file}: {e}")
                except Exception as e:
                    print(f"Error reading {docker_compose_file}: {e}")
    
    return commands_by_project

def print_commands(commands_by_project):
    """Print all extracted commands in a nice format."""
    total_commands = 0
    
    print("=" * 100)
    print("EXTRACTED COMMANDS FROM ALL DOCKER-COMPOSE.YML FILES")
    print("=" * 100)
    
    for project_name in sorted(commands_by_project.keys()):
        commands = commands_by_project[project_name]
        if commands:
            print(f"\n{project_name}:")
            print("-" * 100)
            
            for cmd_info in commands:
                harness_num = cmd_info['harness']
                service = cmd_info['service']
                command = cmd_info['command']
                
                print(f"  Harness: {harness_num}, Service: {service}")
                print(f"  Command: {command}")
                print()
                total_commands += 1
    
    print("=" * 100)
    print(f"TOTAL COMMANDS FOUND: {total_commands}")
    print("=" * 100)

if __name__ == "__main__":
    base_path = "/home/innocent/my_agentic_ai/cvdp_benchmark/gpt-4o-mini_1"
    
    print(f"Searching for docker-compose.yml files in {base_path}...\n")
    
    commands = extract_commands(base_path)
    print_commands(commands)

#!/usr/bin/env python3
"""Orchestrate test execution (CocoTB and lint checks)"""

import logging
from pathlib import Path
from typing import Tuple, List, Dict, Optional
import yaml
import subprocess
import os
import re
import time
import signal
import tempfile
import shutil
from testing.lint_runner import LintRunner

logger = logging.getLogger(__name__)


class TestRunner:
    """Orchestrate test execution"""
    
    def __init__(self, test_timeout: int = 180, lint_timeout: int = 30):
        """
        Initialize test runner
        
        Args:
            test_timeout: Timeout for tests
            lint_timeout: Timeout for lint checks
        """
        self.test_timeout = test_timeout
        self.lint_runner = LintRunner(timeout=lint_timeout)
        self._installed_packages = set()  # Track installed packages
    
    def run(self, code: str) -> Tuple[bool, bool, str, str]:
        """
        Run tests using available tools
        
        Returns:
            Tuple of:
            - compilation_success
            - test_success
            - warnings
            - errors
        """
        logger.info("Starting test execution...")

        # Step 1: Check if code compiles
        logger.info("Step 1: Checking if code compiles...")
        lint_success, lint_errors = self._run_lint_checks(code)
        
        # "" is false. "some error" is true. So if lint_success is False and lint_errors is not empty, it means compilation passed but warnings exist.
        if not lint_success:
            # Compilation failed, return errors
            logger.warning("Compilation failed, skipping testbench execution")
            return False, False, "", lint_errors

        # if lint_errors:
        #     logger.warning(f"Returned lint warnings:")
        #     return True, False, lint_errors, ""

        # Compilation succeeded (possibly with warnings)
        logger.info("Code compiles successfully!")

        # IMPORTANT: Stage the candidate RTL so harness tests the same code we just linted.
        stage_success, stage_error = self._stage_code_for_harness(code)
        if not stage_success:
            logger.error(f"Failed to stage RTL code before harness execution: {stage_error}")
            return False, False, lint_errors, f"Failed to stage RTL code: {stage_error}"

        # Step 2: Run pre-harness testbenches under /code/verif using iverilog/vvp when available.
        logger.info("Step 2: Running pre-harness verif testbenches (if available)...")
        verif_success, verif_errors = self._run_pre_harness_verification()
        verif_warning = ""
        if not verif_success:
            verif_warning = (
                "Your previous code has verification errors in pre-harness verif execution.\n"
                + verif_errors
            )
            logger.warning(verif_warning)
        
        # Step 3: Run harness tests from docker-compose.yml
        logger.info("Step 3: Running test harness from docker-compose.yml...")
        harness_success, harness_errors = self._run_harness_tests()
        
        if not harness_success:
            logger.error(f"Harness tests failed: {harness_errors}")
            combined_errors = harness_errors
            if verif_warning:
                combined_errors = f"{verif_warning}\n\n{harness_errors}"
            # last second place is reserved for warnings, last place always an error whether its compilation or harness.
            return True, False, lint_errors, combined_errors

        logger.info("All tests passed!")
        # If verif had issues but harness passed, keep pass status and surface a warning.
        return True, True, verif_warning, ""

    def _run_pre_harness_verification(self) -> Tuple[bool, str]:
        """
        Run available standalone verif testbenches before harness execution.

        Behavior:
        - Uses iverilog/vvp if present.
        - Executes each discovered testbench independently.
        - Never blocks harness execution; caller decides pass/fail policy.
        """
        verif_dir = Path("/code/verif")
        rtl_dir = Path("/code/rtl")

        if not verif_dir.exists():
            logger.info("No /code/verif directory found, skipping pre-harness verif execution")
            return True, ""

        if shutil.which("iverilog") is None or shutil.which("vvp") is None:
            logger.warning("iverilog/vvp not available, skipping pre-harness verif execution")
            return True, ""

        testbenches = self._discover_testbenches(verif_dir)
        if not testbenches:
            logger.info("No verif testbench files detected, skipping pre-harness verif execution")
            return True, ""

        rtl_sources = self._collect_sv_files(rtl_dir)
        if not rtl_sources:
            logger.info("No RTL sources detected under /code/rtl for pre-harness verif execution")

        support_verif_files = self._collect_verif_support_files(verif_dir, {tb_file for tb_file, _ in testbenches})

        failures: List[str] = []

        for tb_file, top_module in testbenches:
            output_exe = Path(tempfile.gettempdir()) / f"precheck_{tb_file.stem}.out"

            compile_cmd = [
                "iverilog",
                "-g2012",
                "-s",
                top_module,
                "-o",
                str(output_exe),
                *rtl_sources,
                *support_verif_files,
                str(tb_file),
            ]

            logger.info(f"Pre-harness compile: {' '.join(compile_cmd)}")
            comp = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                timeout=self.test_timeout,
                cwd="/code",
            )

            if comp.returncode != 0:
                compile_err = (comp.stderr or comp.stdout or "Compilation failed")[-1200:]
                failures.append(
                    f"[TB compile failed] {tb_file.name} (top={top_module})\n{compile_err}"
                )
                continue

            run_cmd = ["vvp", str(output_exe)]
            logger.info(f"Pre-harness run: {' '.join(run_cmd)}")
            sim = subprocess.run(
                run_cmd,
                capture_output=True,
                text=True,
                timeout=self.test_timeout,
                cwd="/code",
            )

            sim_output = (sim.stdout or "") + ("\n" + sim.stderr if sim.stderr else "")
            output_lower = sim_output.lower()
            explicit_fail = any(token in output_lower for token in ["\nfail", " fail", "assert", "error:"])

            if sim.returncode != 0 or explicit_fail:
                failures.append(
                    f"[TB run failed] {tb_file.name} (top={top_module})\n{sim_output[-1200:]}"
                )

        if failures:
            joined = "\n\n".join(failures)
            return False, joined

        logger.info("Pre-harness verif execution passed for all discovered testbenches")
        return True, ""

    def _discover_testbenches(self, verif_dir: Path) -> List[Tuple[Path, str]]:
        """Discover testbench files and top modules under /code/verif."""
        tbs: List[Tuple[Path, str]] = []
        for file_path in self._collect_sv_files(verif_dir):
            if not file_path.endswith((".sv", ".v")):
                continue

            candidate = Path(file_path)
            stem = candidate.stem.lower()
            if not (stem.startswith("tb_") or stem.endswith("_tb") or "test" in stem):
                continue

            module_name = self._extract_module_name(candidate)
            if module_name:
                tbs.append((candidate, module_name))

        return tbs

    @staticmethod
    def _extract_module_name(file_path: Path) -> Optional[str]:
        """Extract first module name from an SV/V file."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

        match = re.search(r"\bmodule\s+(\w+)", content)
        return match.group(1) if match else None

    @staticmethod
    def _collect_sv_files(root: Path) -> List[str]:
        """Collect Verilog/SystemVerilog files recursively."""
        if not root.exists():
            return []
        exts = {".sv", ".v", ".svh", ".vh"}
        files: List[str] = []
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                files.append(str(p))
        return sorted(files)

    def _collect_verif_support_files(self, verif_dir: Path, tb_files: set[Path]) -> List[str]:
        """Collect non-testbench verif files to support compilation."""
        support: List[str] = []
        for file_path in self._collect_sv_files(verif_dir):
            p = Path(file_path)
            if p in tb_files:
                continue
            support.append(file_path)
        return sorted(support)
    
    def _run_harness_tests(self) -> Tuple[bool, str]:
        """
        Run harness tests by processing docker-compose.yml
        
        This function:
        1. Reads /code/src/docker-compose.yml
        2. For each service, extracts configuration
        3. Installs required dependencies
        4. Loads environment variables
        5. Runs the test command
        6. Returns pass/fail based on exit code
        
        Returns:
            Tuple of (success, error_messages)
        """
        compose_file = Path("/code/docker-compose.yml")
        
        if not compose_file.exists():
            logger.warning("No docker-compose.yml found, skipping harness tests")
            return True, ""  # Not an error, just no harness tests available
        
        try:
            # Parse docker-compose.yml
            with open(compose_file, 'r') as f:
                compose_config = yaml.safe_load(f)
            
            if not compose_config or 'services' not in compose_config:
                logger.warning("No services found in docker-compose.yml")
                return True, ""
            
            services = compose_config['services']
            logger.info(f"Found {len(services)} service(s) in docker-compose.yml: {list(services.keys())}")
            
            # Run tests for each service
            all_passed = True
            error_messages = []
            
            for service_name, service_config in services.items():
                logger.info(f"Processing service: {service_name}")
                
                success, error_msg = self._run_service_test(service_name, service_config)
                
                if not success:
                    all_passed = False
                    error_messages.append(f"Service '{service_name}': {error_msg}")
                else:
                    logger.info(f"Service '{service_name}' passed!")
            
            if all_passed:
                return True, ""
            else:
                return False, "\n".join(error_messages)
        
        except Exception as e:
            logger.error(f"Failed to process docker-compose.yml: {e}")
            return False, f"Failed to process docker-compose.yml: {str(e)}"
    
    def _run_service_test(self, service_name: str, service_config: Dict) -> Tuple[bool, str]:
        """
        Run test for a single service
        
        Args:
            service_name: Name of the service
            service_config: Service configuration from docker-compose.yml
        
        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Step 1: Install dependencies from build (if present)
            if 'build' in service_config:
                logger.info(f"Processing 'build' for service {service_name}")
                build_success, build_error = self._process_build(service_config['build'])
                if not build_success:
                    return False, f"Failed to install build dependencies: {build_error}"
            
            # Step 2: Load environment variables from env_file
            # IMPORTANT: Copy environment AFTER build dependencies are installed
            # because pip install may have updated PYTHONPATH in os.environ
            env_vars = os.environ.copy()
            logger.info(f"Initial PYTHONPATH from os.environ: {env_vars.get('PYTHONPATH', 'NOT SET')}")
            
            if 'env_file' in service_config:
                logger.info(f"Loading environment variables from {service_config['env_file']}")
                env_file_path = Path("/code") / service_config['env_file'].lstrip('./')
                if env_file_path.exists():
                    env_vars.update(self._load_env_file(env_file_path))
                else:
                    logger.warning(f"env_file not found: {env_file_path}")
            
            # Step 3: Extract and process command
            if 'command' not in service_config:
                logger.warning(f"No command specified for service {service_name}")
                return True, ""  # No command to run
            
            command = service_config['command']
            logger.info(f"Command: {command}")
            
            # Step 4: Install runtime dependencies from command (if any)
            runtime_success, runtime_error = self._install_runtime_dependencies(command)
            if not runtime_success:
                logger.warning(f"Failed to install some runtime dependencies: {runtime_error}")
                # Continue anyway, as some installs might be optional
            
            # Keep env_file variables (e.g., MODULE, TOPLEVEL, PYTHONPATH) while also
            # reflecting runtime PYTHONPATH updates performed during pip installs.
            runtime_pythonpath = os.environ.get("PYTHONPATH", "")
            env_pythonpath = env_vars.get("PYTHONPATH", "")
            env_vars["PYTHONPATH"] = self._merge_pythonpath(runtime_pythonpath, env_pythonpath)
            logger.info(f"Effective PYTHONPATH for pytest: {env_vars.get('PYTHONPATH', 'NOT SET')}")

            # Match the direct harness launcher behavior.
            env_vars.setdefault("HOME", "/code/rundir")
            
            # Step 5: Extract pytest command from the full command
            pytest_cmd = self._extract_pytest_command(command)
            if not pytest_cmd:
                logger.warning(f"No pytest command found in service {service_name}")
                return True, ""  # No pytest to run
            
            # Step 6: Normalize known harness-root absolute paths to be valid from /code.
            pytest_cmd = self._normalize_pytest_command_for_code_cwd(pytest_cmd)

            # Step 7: Always run from /code to match agent execution workspace.
            working_dir = '/code'
            
            # Step 8: Run the pytest command
            logger.info(f"Running pytest: {pytest_cmd}")
            logger.info(f"Working directory: {working_dir}")
            logger.info(f"PYTHONPATH being passed to pytest: {env_vars.get('PYTHONPATH', 'NOT SET')}")
            
            mem_kill_threshold = float(os.getenv("SIM_MEMORY_KILL_THRESHOLD_PCT", "90"))
            killed_by_watchdog = False

            # Stream subprocess output to files to avoid additional memory pressure.
            with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", errors="replace", delete=True) as stdout_f, \
                 tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", errors="replace", delete=True) as stderr_f:

                proc = subprocess.Popen(
                    pytest_cmd,
                    shell=True,
                    cwd=working_dir,
                    env=env_vars,
                    stdout=stdout_f,
                    stderr=stderr_f,
                    text=True,
                    start_new_session=True,
                )

                start_time = time.time()

                while proc.poll() is None:
                    elapsed = time.time() - start_time
                    mem_pct = self._get_system_memory_usage_percent()

                    if mem_pct is not None and mem_pct >= mem_kill_threshold:
                        killed_by_watchdog = True
                        logger.error(
                            f"Simulation watchdog triggered: system memory usage {mem_pct:.2f}% >= {mem_kill_threshold:.2f}%"
                        )
                        self._terminate_process_group(proc)
                        break

                    if elapsed > self.test_timeout:
                        self._terminate_process_group(proc)
                        raise subprocess.TimeoutExpired(pytest_cmd, self.test_timeout)

                    time.sleep(1)

                # Ensure process is reaped after potential termination.
                returncode = proc.wait(timeout=10)

                stdout_f.flush()
                stderr_f.flush()
                stdout_f.seek(0)
                stderr_f.seek(0)
                stdout = stdout_f.read()
                stderr = stderr_f.read()

            self._log_pytest_output(service_name, pytest_cmd, stdout, stderr, returncode)
            
            # Step 9: Check exit code
            if killed_by_watchdog:
                logger.error("✗ Service '%s' tests stopped due to stucked testbench simulation or high memory usage detected", service_name)
                return False, "Testbench simulation stuck or high memory usage detected; process terminated."
            elif returncode == 0:
                logger.info(f"✓ Service '{service_name}' tests passed (exit code: 0)")
                return True, ""
            else:
                logger.error(f"✗ Service '{service_name}' tests failed (exit code: {returncode})")
                error_output = stderr if stderr else stdout
                logger.info(f"Tests failed with exit code {returncode}")
                return False, error_output[-500:]
        
        except subprocess.TimeoutExpired:
            return False, f"Test execution timed out (>180s)"
        except Exception as e:
            logger.error(f"Error running service {service_name}: {e}")
            return False, f"Error running test: {str(e)}"

    def _log_pytest_output(self, service_name: str, pytest_cmd: str, stdout: str, stderr: str, returncode: int) -> None:
        """
        Log full pytest output with clear visual separators for easier debugging.
        """
        separator = "=" * 53  # =====================================================

        logger.info(separator)
        logger.info(f"PYTEST RESULTS - Service: {service_name}")
        logger.info(separator)
        logger.info(f"Command: {pytest_cmd}")
        logger.info(f"Exit code: {returncode}")

        stdout = stdout if stdout else "<empty>"
        stderr = stderr if stderr else "<empty>"

        logger.info(separator)
        logger.info("PYTEST STDOUT")
        logger.info(separator)
        logger.info(stdout)

        logger.info(separator)
        logger.info("PYTEST STDERR")
        logger.info(separator)
        logger.info(stderr)
        logger.info(separator)

    def _terminate_process_group(self, proc: subprocess.Popen) -> None:
        """Terminate a subprocess group created with start_new_session=True."""
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            time.sleep(1)
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning(f"Failed to terminate process group for pid {proc.pid}: {e}")

    def _get_system_memory_usage_percent(self) -> Optional[float]:
        """Return host memory usage percentage using /proc/meminfo, or None if unavailable."""
        try:
            mem_total_kb = None
            mem_available_kb = None

            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_total_kb = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        mem_available_kb = int(line.split()[1])

            if not mem_total_kb or mem_available_kb is None:
                return None

            used_pct = ((mem_total_kb - mem_available_kb) / mem_total_kb) * 100.0
            return used_pct
        except Exception:
            return None

    def _normalize_pytest_command_for_code_cwd(self, pytest_cmd: str) -> str:
        """
        Normalize known harness absolute paths so commands run reliably from /code.

        Converts root-anchored harness paths such as /src/test_runner.py or
        cache_dir=/rundir/.cache to ./src/test_runner.py and ./rundir/.cache.
        Leaves /code/... paths unchanged.
        """
        if not pytest_cmd:
            return pytest_cmd

        normalized = pytest_cmd
        roots = ("src", "rtl", "verif", "docs", "rundir")

        for root in roots:
            pattern = rf'(^|[\s=\'\"])/{root}(?=/|$)'
            normalized = re.sub(pattern, rf'\1./{root}', normalized)

        if normalized != pytest_cmd:
            logger.info("Normalized pytest command for /code working directory:")
            logger.info(f"  Before: {pytest_cmd}")
            logger.info(f"  After:  {normalized}")

        return normalized

    def _stage_code_for_harness(self, code: str) -> Tuple[bool, str]:
        """
        Write candidate RTL into /code/rtl before running harness tests.

        Harness tests compile from VERILOG_SOURCES in /code/rtl, so failing to stage
        here can produce stale-code false positives/negatives.
        """
        try:
            target_path = self._resolve_rtl_target_path()
            if target_path is None:
                return False, "No RTL target found from VERILOG_SOURCES/TOPLEVEL or existing RTL files"

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(code)
            logger.info(f"Staged candidate RTL for harness at: {target_path}")
            return True, ""
        except Exception as e:
            return False, str(e)

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

    def _resolve_rtl_target_path(self) -> Optional[Path]:
        """Resolve the RTL file path to write based on VERILOG_SOURCES, then TOPLEVEL."""
        raw_sources = (os.getenv("VERILOG_SOURCES") or "").strip()
        toplevel = os.getenv("TOPLEVEL")

        if raw_sources:
            explicit_sources: list[Path] = []
            wildcard_suffixes: list[str] = []

            for source in raw_sources.split():
                source = source.strip()
                if not source:
                    continue

                source_path = Path(source)
                source_name = source_path.name

                # Wildcard source (e.g. /code/rtl/*.sv): use TOPLEVEL with wildcard extension.
                if "*" in source_name:
                    source_suffix = source_path.suffix
                    if source_suffix:
                        wildcard_suffixes.append(source_suffix)
                    continue

                explicit_sources.append(source_path)

            if len(explicit_sources) == 1:
                return explicit_sources[0]

            if len(explicit_sources) > 1:
                if toplevel:
                    return max(
                        explicit_sources,
                        key=lambda p: self._get_string_similarity(p.stem, toplevel),
                    )
                return explicit_sources[0]

            if wildcard_suffixes and toplevel:
                return Path("/code/rtl") / f"{toplevel}{wildcard_suffixes[0]}"

        if toplevel:
            return Path("/code/rtl") / f"{toplevel}.sv"

        rtl_dir = Path("/code/rtl")
        candidates = sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v")))
        if candidates:
            return candidates[0]

        return None

    def _merge_pythonpath(self, runtime_pythonpath: str, env_pythonpath: str) -> str:
        """
        Merge PYTHONPATH values while preserving order and removing duplicates.
        """
        merged = []

        for source in (runtime_pythonpath, env_pythonpath):
            if not source:
                continue
            for entry in source.split(":"):
                entry = entry.strip()
                if entry and entry not in merged:
                    merged.append(entry)

        return ":".join(merged)
    
    def _process_build(self, build_config) -> Tuple[bool, str]:
        """
        Process 'build' section to install dependencies
        
        Handles:
        - build: .
        - build: {dockerfile: path/to/Dockerfile}
        - build: {context: ., dockerfile: Dockerfile}
        
        Args:
            build_config: Build configuration (string or dict)
        
        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Determine Dockerfile path
            if isinstance(build_config, str):
                # build: .
                dockerfile_path = Path("/code") / "Dockerfile"
            elif isinstance(build_config, dict):
                # build: {dockerfile: src/Dockerfile.synth}
                dockerfile = build_config.get('dockerfile', 'Dockerfile')
                context = build_config.get('context', '.')
                rel_context = context.lstrip('./')
                rel_dockerfile = dockerfile.lstrip('./')

                candidates = [
                    Path("/code/src") / rel_context / rel_dockerfile,
                    Path("/code") / rel_context / rel_dockerfile,
                ]

                dockerfile_path = next((path for path in candidates if path.exists()), candidates[0])
            else:
                logger.warning(f"Unknown build config format: {build_config}")
                return True, ""
            
            if not dockerfile_path.exists():
                logger.warning(f"Dockerfile not found: {dockerfile_path}, skipping build dependencies")
                return True, ""
            
            # Parse Dockerfile for RUN commands (ignore FROM)
            with open(dockerfile_path, 'r') as f:
                dockerfile_content = f.read()

            logger.info(f"Processing Dockerfile: \n{dockerfile_content}")
            
            # Extract RUN commands
            run_commands = re.findall(r'^RUN\s+(.+?)(?=\n(?:FROM|RUN|COPY|ADD|CMD|ENTRYPOINT)|$)', 
                                     dockerfile_content, 
                                     re.MULTILINE | re.DOTALL)
            
            if not run_commands:
                logger.info("No RUN commands found in Dockerfile")
                return True, ""
            
            # Execute only pip install commands
            for run_cmd in run_commands:
                # Clean up command (remove line continuations)
                run_cmd = run_cmd.replace('\\\n', ' ').replace('\\', '').strip()
                
                # Only process pip install commands
                if 'pip' in run_cmd and 'install' in run_cmd:
                    logger.info(f"Installing from Dockerfile: {run_cmd}")
                    success, error = self._execute_pip_install(run_cmd)
                    if not success:
                        logger.warning(f"Failed to install: {error}")
                        # Continue with other installs
            
            return True, ""
        
        except Exception as e:
            logger.error(f"Error processing build: {e}")
            return False, str(e)
    
    def _install_runtime_dependencies(self, command: str) -> Tuple[bool, str]:
        """
        Extract and install dependencies from command string
        
        Looks for patterns like:
        - pip3 install package
        - pip install --upgrade package==1.9.2
        
        Args:
            command: Command string from docker-compose.yml
        
        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Extract pip install commands from the full command
            # Pattern: pip/pip3 install ... (before pytest or semicolon)
            pip_patterns = [
                r'pip3?\s+install\s+[^;]+',
                r'python3?\s+-m\s+pip\s+install\s+[^;]+'
            ]
            
            for pattern in pip_patterns:
                matches = re.findall(pattern, command, re.IGNORECASE)
                for pip_cmd in matches:
                    logger.info(f"Installing runtime dependency: {pip_cmd}")
                    success, error = self._execute_pip_install(pip_cmd)
                    if not success:
                        logger.warning(f"Failed to install: {error}")
                        # Continue with other installs
            
            return True, ""
        
        except Exception as e:
            return False, str(e)
    
    def _execute_pip_install(self, pip_command: str) -> Tuple[bool, str]:
        """
        Execute a pip install command, avoiding duplicate installs
        
        Args:
            pip_command: Pip install command string
        
        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Extract package names to track installed packages
            packages = self._extract_package_names(pip_command)
            logger.info(f"Extracted package names: {packages}")
            
            # Check if already installed
            if packages and all(pkg in self._installed_packages for pkg in packages):
                logger.info(f"Packages already installed: {packages}")
                return True, ""
            
            # Modify pip command to install to a writable target directory and avoid cache permissions issues
            original_command = pip_command
            if "pip install" in pip_command or "pip3 install" in pip_command:
                pip_command = pip_command.replace("--user", "")  # remove --user if it exists to avoid conflicts
                if "--target" not in pip_command:
                    pip_command = re.sub(r'(pip3?\s+install)', r'\1 --no-cache-dir --target /tmp/pip-packages', pip_command, flags=re.IGNORECASE)
            
            logger.info(f"Modified pip command: {pip_command}")
            
            # Ensure future subprocesses can find the installed packages
            current_pythonpath = os.environ.get("PYTHONPATH", "")
            if "/tmp/pip-packages" not in current_pythonpath:
                os.environ["PYTHONPATH"] = f"/tmp/pip-packages:{current_pythonpath}".strip(":")
                logger.info(f"Updated PYTHONPATH to include /tmp/pip-packages")
            
            # Execute pip install
            logger.info(f"Executing pip install command: {pip_command}")
            result = subprocess.run(
                pip_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            # Log detailed output
            logger.info(f"pip install exit code: {result.returncode}")
            if result.stdout:
                logger.info(f"pip install stdout:\n{result.stdout}")
            if result.stderr:
                logger.info(f"pip install stderr:\n{result.stderr}")
            
            # Check what was installed in the target directory
            try:
                if os.path.exists("/tmp/pip-packages"):
                    installed_contents = os.listdir("/tmp/pip-packages")
                    logger.info(f"Contents of /tmp/pip-packages: {installed_contents}")
                else:
                    logger.warning("/tmp/pip-packages directory does not exist")
            except Exception as e:
                logger.warning(f"Could not list /tmp/pip-packages: {e}")
            
            # Mark packages as installed
            self._installed_packages.update(packages)
            logger.info(f"Marked packages as installed: {packages}")
            logger.info(f"Total installed packages: {self._installed_packages}")
            
            if result.returncode != 0:
                # Log but don't fail (might be already installed or optional)
                logger.warning(f"pip install returned {result.returncode}: {result.stderr}")
            else:
                logger.info(f"✓ Successfully installed: {packages}")
            
            # # Verify installation by checking if package is importable
            # for pkg in packages:
            #     try:
            #         # Try to verify the package was installed
            #         verify_cmd = f"python3 -c 'import {pkg}; print(\"{pkg} successfully imported\")'"
            #         verify_result = subprocess.run(
            #             verify_cmd,
            #             shell=True,
            #             capture_output=True,
            #             text=True,
            #             timeout=5,
            #             env=os.environ.copy()
            #         )
            #         if verify_result.returncode == 0:
            #             logger.info(f"✓ Verified: {pkg} is importable - {verify_result.stdout.strip()}")
            #         else:
            #             logger.warning(f"✗ Could not import {pkg}: {verify_result.stderr}")
            #     except Exception as e:
            #         logger.warning(f"Could not verify {pkg}: {e}")
            
            return True, ""
        except subprocess.TimeoutExpired:
            logger.error("pip install timed out after 120 seconds")
            return False, "pip install timed out"
        except Exception as e:
            logger.error(f"Exception during pip install: {str(e)}")
            return False, str(e)
    
    def _extract_package_names(self, pip_command: str) -> List[str]:
        """
        Extract package names from pip install command
        
        Args:
            pip_command: Pip command string
        
        Returns:
            List of package names
        """
        # Remove pip install prefix and flags
        cleaned = re.sub(r'pip3?\s+install\s+', '', pip_command, flags=re.IGNORECASE)
        cleaned = re.sub(r'--[a-z-]+', '', cleaned)  # Remove flags like --upgrade
        cleaned = re.sub(r'2>/dev/null', '', cleaned)  # Remove redirects
        
        # Split by spaces and extract package names (before ==, >=, etc.)
        packages = []
        for part in cleaned.split():
            part = part.strip('"\'')
            if part and not part.startswith('-'):
                # Extract package name (before version specifier)
                pkg_name = re.split(r'[=<>!]', part)[0].strip()
                if pkg_name:
                    packages.append(pkg_name)
        
        return packages
    
    def _extract_pytest_command(self, command: str) -> Optional[str]:
        """
        Extract pytest command from the full command string
        
        Handles commands like:
        - pytest /src/test.py -v
        - sh -c 'pip install ...; pytest /src/test.py'
        - /bin/sh -c "pytest -s -o cache_dir=/rundir/harness/.cache /src/test_runner.py
        - python3 /src/test_runner.py
        
        Args:
            command: Full command string (may have incomplete quotes)
        
        Returns:
            Pytest command or None
        """
        # Remove shell wrapper if present: sh -c, /bin/sh -c, bash -c
        if re.search(r'(sh|bash|/bin/sh)\s+-c\s+', command):
            # Extract content after -c (handle both quoted and unquoted)
            # Pattern: -c followed by optional whitespace and optional quote
            match = re.search(r'(?:sh|bash|/bin/sh)\s+-c\s+["\']?(.+?)(?:["\'])?$', command, re.DOTALL)
            if match:
                command = match.group(1).strip()
                # Remove trailing quote if present
                if command and command[-1] in '"\'':
                    command = command[:-1]
        
        # Find pytest command (after last semicolon if chained)
        parts = command.split(';')
        for part in reversed(parts):
            part = part.strip()
            if 'pytest' in part:
                return part
            # Also check for python test_runner.py pattern
            if 'python' in part and 'test' in part:
                return part
        
        return None
    
    def _modify_paths(self, pytest_cmd: str) -> str:
        """
        Modify absolute paths in command to relative paths by adding . before /
        except paths starting with /code (treated as home path).

        Examples:
            Input:  "pytest -s -o cache_dir=/rundir/cache /src/test.py -v"
            Output: "pytest -s -o cache_dir=./rundir/cache ./src/test.py -v"

            Input:  "pytest /code/rtl/test.py -v"
            Output: "pytest /code/rtl/test.py -v"   # unchanged
        """
        if not pytest_cmd:
            return pytest_cmd

        tokens = pytest_cmd.split()
        modified_tokens = []

        for token in tokens:
            if '/' in token:
                slash_pos = token.find('/')

                # Case 1: path starts with /
                if slash_pos == 0:
                    path = token

                    # Skip if path starts with /code
                    if path.startswith("/code"):
                        modified_tokens.append(token)
                        continue

                    token = '.' + path

                # Case 2: path appears after =
                elif slash_pos > 0 and token[slash_pos - 1] == '=':
                    prefix = token[:slash_pos]
                    path = token[slash_pos:]

                    # Skip if path starts with /code
                    if path.startswith("/code"):
                        modified_tokens.append(token)
                        continue

                    token = prefix + '.' + path

            modified_tokens.append(token)

        modified_cmd = ' '.join(modified_tokens)

        if modified_cmd != pytest_cmd:
            logger.info("Modified paths in command:")
            logger.info(f"  Before: {pytest_cmd}")
            logger.info(f"  After:  {modified_cmd}")

        return modified_cmd
    
    # def _modify_paths(self, pytest_cmd: str) -> str:
    #     """
    #     Modify absolute paths in command to relative paths by adding . before /
        
    #     Simple logic: Find any token starting with / and prepend . to it
        
    #     Examples:
    #         Input:  "pytest -s -o cache_dir=/rundir/cache /src/test.py -v"
    #         Output: "pytest -s -o cache_dir=./rundir/cache ./src/test.py -v"
            
    #         Input:  "pytest /code/rtl/test.py -v"
    #         Output: "pytest ./code/rtl/test.py -v"
        
    #     Args:
    #         pytest_cmd: Original pytest command
        
    #     Returns:
    #         Modified command with . prepended to absolute paths
    #     """
    #     if not pytest_cmd:
    #         return pytest_cmd
        
    #     # Split command into tokens (by spaces)
    #     tokens = pytest_cmd.split()
    #     modified_tokens = []
        
    #     for token in tokens:
    #         # Check if this token contains a path starting with /
    #         if '/' in token:
    #             # Find position of first /
    #             slash_pos = token.find('/')
                
    #             # Check if / is at the start or after = (for options like cache_dir=/path)
    #             if slash_pos == 0:
    #                 # Path at start: /src/test.py -> ./src/test.py
    #                 token = '.' + token
    #             elif slash_pos > 0 and token[slash_pos - 1] == '=':
    #                 # Path after =: cache_dir=/rundir -> cache_dir=./rundir
    #                 prefix = token[:slash_pos]
    #                 path = token[slash_pos:]
    #                 token = prefix + '.' + path
            
    #         modified_tokens.append(token)
        
    #     modified_cmd = ' '.join(modified_tokens)
        
    #     if modified_cmd != pytest_cmd:
    #         logger.info(f"Modified paths in command:")
    #         logger.info(f"  Before: {pytest_cmd}")
    #         logger.info(f"  After:  {modified_cmd}")
        
    #     return modified_cmd
    
    def _load_env_file(self, env_file_path: Path) -> Dict[str, str]:
        """
        Load environment variables from .env file
        
        Args:
            env_file_path: Path to .env file
        
        Returns:
            Dictionary of environment variables
        """
        env_vars = {}
        
        try:
            with open(env_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse KEY=VALUE
                    if '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
            
            logger.info(f"Loaded {len(env_vars)} environment variables")
            return env_vars
        
        except Exception as e:
            logger.error(f"Error loading env file: {e}")
            return {}
    
    def _run_lint_checks(self, code: str) -> Tuple[bool, str]:
        """
        Run lint checks on RTL code string
        
        Args:
            code: RTL code as string
            
        Returns:
            Tuple of (success, error_messages)
        """
        if not code or not code.strip():
            logger.warning("No RTL code provided for linting")
            return False, "No RTL code provided"
        
        return self.lint_runner.run(code)
    
    
    def categorize_errors(self, errors: str) -> str:
        """
        Categorize error messages
        
        Args:
            errors: Error messages from tests
            
        Returns:
            Error category (syntax, logic, timing, etc.)
        """
        errors_lower = errors.lower()
        
        # Syntax errors
        if any(kw in errors_lower for kw in ["syntax error", "parse error", "unexpected", "expected"]):
            return "syntax"
        
        # Undefined/undeclared
        if any(kw in errors_lower for kw in ["undeclared", "undefined", "not declared"]):
            return "undeclared"
        
        # Type errors
        if any(kw in errors_lower for kw in ["type mismatch", "incompatible types"]):
            return "type"
        
        # Width mismatches
        if any(kw in errors_lower for kw in ["width", "bit width", "size mismatch"]):
            return "width"
        
        # Latch inference
        if "latch" in errors_lower:
            return "latch"
        
        # Timing
        if any(kw in errors_lower for kw in ["timing", "setup", "hold"]):
            return "timing"
        
        # Default
        return "general"

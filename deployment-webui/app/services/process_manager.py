"""Process manager for async subprocess execution with output streaming."""

import asyncio
import os
from pathlib import Path
from typing import Optional, Dict, List, Callable, Awaitable
from dataclasses import dataclass, field


@dataclass
class ProcessResult:
    """Result of a process execution."""
    success: bool
    return_code: int
    output: str


@dataclass
class ProcessManager:
    """Manages async subprocess execution with streaming output."""

    current_process: Optional[asyncio.subprocess.Process] = field(default=None)
    cancelled: bool = field(default=False)

    async def run_command(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
        on_output: Optional[Callable[[str], Awaitable[None]]] = None,
        timeout: Optional[float] = None
    ) -> ProcessResult:
        """
        Run a command asynchronously with output streaming.

        Args:
            cmd: Command and arguments to run
            cwd: Working directory
            env: Additional environment variables
            on_output: Async callback for each output line
            timeout: Command timeout in seconds

        Returns:
            ProcessResult with success status and output
        """
        self.cancelled = False

        # Merge environment
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        output_lines = []

        try:
            self.current_process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd) if cwd else None,
                env=merged_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.PIPE
            )

            # Send 'y' responses for auto-confirm
            if self.current_process.stdin:
                try:
                    self.current_process.stdin.write(b"y\n" * 10)
                    await self.current_process.stdin.drain()
                    self.current_process.stdin.close()
                except (BrokenPipeError, ConnectionResetError):
                    pass

            # Read output line by line
            async def read_output():
                while True:
                    if self.cancelled:
                        break
                    line = await self.current_process.stdout.readline()
                    if not line:
                        break
                    decoded_line = line.decode('utf-8', errors='replace').rstrip()
                    if decoded_line:
                        output_lines.append(decoded_line)
                        if on_output:
                            await on_output(decoded_line)

            if timeout:
                try:
                    await asyncio.wait_for(read_output(), timeout=timeout)
                except asyncio.TimeoutError:
                    await self.cancel()
                    return ProcessResult(
                        success=False,
                        return_code=-1,
                        output="\n".join(output_lines) + "\n[TIMEOUT]"
                    )
            else:
                await read_output()

            await self.current_process.wait()

            return ProcessResult(
                success=self.current_process.returncode == 0 and not self.cancelled,
                return_code=self.current_process.returncode or 0,
                output="\n".join(output_lines)
            )

        except Exception as e:
            return ProcessResult(
                success=False,
                return_code=-1,
                output=f"Error: {str(e)}"
            )
        finally:
            self.current_process = None

    async def run_command_simple(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = 60
    ) -> ProcessResult:
        """
        Run a command and capture output without streaming.

        Args:
            cmd: Command and arguments to run
            cwd: Working directory
            env: Additional environment variables
            timeout: Command timeout in seconds

        Returns:
            ProcessResult with success status and output
        """
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd) if cwd else None,
                env=merged_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            return ProcessResult(
                success=process.returncode == 0,
                return_code=process.returncode or 0,
                output=stdout.decode('utf-8', errors='replace')
            )

        except asyncio.TimeoutError:
            return ProcessResult(
                success=False,
                return_code=-1,
                output="[TIMEOUT]"
            )
        except Exception as e:
            return ProcessResult(
                success=False,
                return_code=-1,
                output=f"Error: {str(e)}"
            )

    async def cancel(self) -> bool:
        """Cancel the current running process."""
        self.cancelled = True
        if self.current_process:
            try:
                self.current_process.terminate()
                # Give it a moment to terminate gracefully
                await asyncio.sleep(1)
                if self.current_process.returncode is None:
                    self.current_process.kill()
                return True
            except Exception:
                return False
        return False

    @property
    def is_running(self) -> bool:
        """Check if a process is currently running."""
        return self.current_process is not None and self.current_process.returncode is None

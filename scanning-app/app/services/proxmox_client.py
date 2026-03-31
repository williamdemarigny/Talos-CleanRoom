"""Async Proxmox VE REST API client for target VM lifecycle management.

Handles cloning templates, starting/stopping VMs, querying status,
and retrieving guest IP addresses via the QEMU guest agent.
"""

import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class ProxmoxError(Exception):
    """Raised when a Proxmox API call fails."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class ProxmoxClient:
    """Async client for Proxmox VE REST API."""

    def __init__(self, base_url: str, api_token: str):
        """Initialize with Proxmox API URL and token.

        Args:
            base_url: e.g. "https://10.83.2.20:8006"
            api_token: PVE API token, format "user@realm!tokenid=secret"
        """
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=f"{self._base_url}/api2/json",
            headers={"Authorization": f"PVEAPIToken={api_token}"},
            verify=False,
            timeout=30.0,
        )

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    # ── Core API helpers ──────────────────────────────────────────

    @staticmethod
    def _sanitize_response(text: str, max_len: int = 200) -> str:
        """Truncate response text to prevent leaking sensitive data in logs."""
        if not text:
            return ""
        sanitized = text[:max_len]
        if len(text) > max_len:
            sanitized += "...[truncated]"
        return sanitized

    async def _get(self, path: str) -> dict:
        resp = await self._client.get(path)
        if resp.status_code != 200:
            raise ProxmoxError(
                f"GET {path} failed: {resp.status_code} {self._sanitize_response(resp.text)}",
                resp.status_code,
            )
        return resp.json().get("data", {})

    async def _post(self, path: str, data: Optional[dict] = None) -> dict:
        resp = await self._client.post(path, data=data or {})
        if resp.status_code not in (200, 201):
            raise ProxmoxError(
                f"POST {path} failed: {resp.status_code} {self._sanitize_response(resp.text)}",
                resp.status_code,
            )
        return resp.json().get("data", {})

    async def _put(self, path: str, data: Optional[dict] = None) -> dict:
        resp = await self._client.put(path, data=data or {})
        if resp.status_code != 200:
            raise ProxmoxError(
                f"PUT {path} failed: {resp.status_code} {self._sanitize_response(resp.text)}",
                resp.status_code,
            )
        return resp.json().get("data", {})

    async def _delete(self, path: str) -> dict:
        resp = await self._client.delete(path)
        if resp.status_code != 200:
            raise ProxmoxError(
                f"DELETE {path} failed: {resp.status_code} {self._sanitize_response(resp.text)}",
                resp.status_code,
            )
        return resp.json().get("data", {})

    # ── Task tracking ─────────────────────────────────────────────

    async def _wait_for_task(self, node: str, upid: str, timeout: int = 300):
        """Poll a Proxmox task until completion."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            status = await self._get(f"/nodes/{node}/tasks/{upid}/status")
            if status.get("status") == "stopped":
                if status.get("exitstatus") != "OK":
                    raise ProxmoxError(
                        f"Task {upid} failed: {status.get('exitstatus')}"
                    )
                return status
            await asyncio.sleep(2)
        raise ProxmoxError(f"Task {upid} timed out after {timeout}s")

    # ── Node discovery ────────────────────────────────────────────

    async def get_nodes(self) -> list[str]:
        """Return list of online Proxmox node names."""
        nodes = await self._get("/nodes")
        return [
            n["node"] for n in nodes
            if isinstance(n, dict) and n.get("status") == "online"
        ]

    # ── Template operations ───────────────────────────────────────

    async def list_templates(
        self, node: str, vmid_min: int = 4000, vmid_max: int = 4099
    ) -> list[dict]:
        """List VM templates in a VMID range on a node."""
        vms = await self._get(f"/nodes/{node}/qemu")
        return [
            {"vmid": vm["vmid"], "name": vm.get("name", ""), "node": node}
            for vm in vms
            if isinstance(vm, dict)
            and vm.get("template", 0) == 1
            and vmid_min <= vm.get("vmid", 0) <= vmid_max
        ]

    # ── VM lifecycle ──────────────────────────────────────────────

    async def clone_template(
        self,
        node: str,
        template_vmid: int,
        new_vmid: int,
        name: str,
        full: bool = True,
    ) -> None:
        """Clone a template VM to a new VMID."""
        logger.info(
            "Cloning template %d -> %d (%s) on %s",
            template_vmid, new_vmid, name, node,
        )
        data = {
            "newid": new_vmid,
            "name": name,
            "full": int(full),
        }
        result = await self._post(
            f"/nodes/{node}/qemu/{template_vmid}/clone", data=data
        )
        # Clone returns a task UPID — wait for it
        if isinstance(result, str):
            upid = result
        elif isinstance(result, dict):
            upid = result.get("data", result) if "data" in result else None
        else:
            raise ProxmoxError(f"Clone returned unexpected format: {result}")
        if upid:
            await self._wait_for_task(node, upid, timeout=600)
        else:
            raise ProxmoxError("Clone did not return a task UPID")
        # Verify VM actually exists after clone
        if not await self.vm_exists(node, new_vmid):
            raise ProxmoxError(
                f"Clone task completed but VM {new_vmid} not found on {node}"
            )
        logger.info("Clone complete: VMID %d", new_vmid)

    async def configure_vm(
        self,
        node: str,
        vmid: int,
        ip: str,
        gateway: str,
        netmask: str = "255.255.255.0",
    ) -> None:
        """Configure cloud-init IP settings on a cloned VM."""
        # Convert netmask to CIDR prefix length
        cidr = sum(bin(int(x)).count("1") for x in netmask.split("."))
        ipconfig = f"ip={ip}/{cidr},gw={gateway}"
        logger.info("Configuring VM %d: %s", vmid, ipconfig)
        await self._put(
            f"/nodes/{node}/qemu/{vmid}/config",
            data={"ipconfig0": ipconfig},
        )

    async def start_vm(self, node: str, vmid: int) -> None:
        """Start a VM."""
        logger.info("Starting VM %d on %s", vmid, node)
        result = await self._post(f"/nodes/{node}/qemu/{vmid}/status/start")
        upid = result if isinstance(result, str) else None
        if upid:
            await self._wait_for_task(node, upid, timeout=120)

    async def stop_vm(self, node: str, vmid: int) -> None:
        """Stop a VM (force)."""
        logger.info("Stopping VM %d on %s", vmid, node)
        try:
            result = await self._post(
                f"/nodes/{node}/qemu/{vmid}/status/stop",
                data={"forceStop": 1},
            )
            upid = result if isinstance(result, str) else None
            if upid:
                await self._wait_for_task(node, upid, timeout=120)
        except ProxmoxError as e:
            # VM may already be stopped
            if "not running" not in str(e).lower():
                raise

    async def destroy_vm(self, node: str, vmid: int) -> None:
        """Delete a VM and its disks."""
        logger.info("Destroying VM %d on %s", vmid, node)
        # Ensure stopped first
        try:
            await self.stop_vm(node, vmid)
        except ProxmoxError:
            pass
        await asyncio.sleep(2)
        await self._delete(f"/nodes/{node}/qemu/{vmid}?destroy-unreferenced-disks=1&purge=1")
        logger.info("VM %d destroyed", vmid)

    # ── Status & IP queries ───────────────────────────────────────

    async def get_vm_status(self, node: str, vmid: int) -> dict:
        """Get VM status (running, stopped, etc.)."""
        return await self._get(f"/nodes/{node}/qemu/{vmid}/status/current")

    async def get_vm_ip(self, node: str, vmid: int) -> Optional[str]:
        """Get VM IP address via QEMU guest agent.

        Returns the first non-loopback IPv4 address, or None.
        """
        try:
            data = await self._get(
                f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces"
            )
            result = data.get("result", data) if isinstance(data, dict) else data
            if not isinstance(result, list):
                return None
            for iface in result:
                if iface.get("name") == "lo":
                    continue
                for addr in iface.get("ip-addresses", []):
                    if addr.get("ip-address-type") == "ipv4":
                        ip = addr.get("ip-address", "")
                        if ip and not ip.startswith("127."):
                            return ip
        except ProxmoxError:
            return None
        return None

    async def wait_for_ip(
        self, node: str, vmid: int, timeout: int = 180
    ) -> Optional[str]:
        """Poll until a VM has an IP address from the guest agent."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            ip = await self.get_vm_ip(node, vmid)
            if ip:
                logger.info("VM %d has IP: %s", vmid, ip)
                return ip
            await asyncio.sleep(5)
        logger.warning("VM %d: timed out waiting for IP after %ds", vmid, timeout)
        return None

    async def vm_exists(self, node: str, vmid: int) -> bool:
        """Check if a VM exists on a node."""
        try:
            await self._get(f"/nodes/{node}/qemu/{vmid}/status/current")
            return True
        except ProxmoxError:
            return False

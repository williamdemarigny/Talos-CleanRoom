"""Target Lab service — manages Metasploitable3 target VM lifecycle.

Handles deployment, destruction, IP allocation, and TTL-based cleanup
of ephemeral target VMs cloned from Proxmox templates.
"""

import asyncio
import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, and_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import engine as db_engine
from app.db.models import TargetVM
from app.services.proxmox_client import ProxmoxClient, ProxmoxError

logger = logging.getLogger(__name__)

# Template metadata for UI display
TEMPLATES = {
    "ubuntu": {
        "name": "Metasploitable3 — Ubuntu 14.04",
        "os": "Ubuntu 14.04 LTS",
        "description": (
            "Intentionally vulnerable Linux VM with exploitable services "
            "including MySQL, Apache, phpMyAdmin, ProFTPD, Samba, UnrealIRCd, "
            "Drupal, CUPS, SSH (weak config), and more."
        ),
        "services": [
            "MySQL", "Apache (Continuum, Struts)", "PHP 5.4.5", "phpMyAdmin",
            "ProFTPD", "Docker", "Samba", "Sinatra", "UnrealIRCd", "CUPS",
            "Drupal", "SSH (weak config)", "knockd",
        ],
        "credentials": "vagrant / vagrant",
        "specs": {"cpu": 2, "memory_mb": 4096, "disk_gb": 40},
    },
    "windows": {
        "name": "Metasploitable3 — Windows Server 2008 R2",
        "os": "Windows Server 2008 R2",
        "description": (
            "Intentionally vulnerable Windows VM with exploitable services "
            "including IIS, Jenkins, Apache Tomcat, GlassFish, ElasticSearch, "
            "WordPress, ManageEngine, WebDAV, WinRM, SNMP, and more."
        ),
        "services": [
            "IIS (FTP + HTTP)", "Jenkins", "Apache Tomcat", "GlassFish",
            "ElasticSearch", "WordPress", "ManageEngine", "Apache Axis2",
            "WebDAV", "WinRM", "SNMP", "JMX", "MySQL", "psexec/SMB", "RDP",
        ],
        "credentials": "vagrant / vagrant",
        "specs": {"cpu": 2, "memory_mb": 4096, "disk_gb": 60},
        "max_instances": 1,  # Windows lacks cloud-init — fixed IP
    },
}

# Active statuses (not destroyed/error)
_ACTIVE_STATUSES = ("deploying", "running", "stopping")

# Advisory lock ID for serializing VM allocation (PostgreSQL pg_advisory_lock)
_ALLOCATION_LOCK_ID = 839271


def _get_session_factory():
    """Get the async session factory, raising if DB not initialized."""
    factory = db_engine.get_session_factory()
    if factory is None:
        raise TargetLabError("Database not initialized.")
    return factory


class TargetLabError(Exception):
    """Raised for Target Lab operation failures."""
    pass


class TargetLabService:
    """Manages Metasploitable3 target VM lifecycle via Proxmox API."""

    def __init__(self):
        settings = get_settings()
        if settings.proxmox_api_url and settings.proxmox_api_token:
            self._client = ProxmoxClient(
                settings.proxmox_api_url, settings.proxmox_api_token
            )
        else:
            self._client = None
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return (
            self._settings.target_lab_enabled
            and self._client is not None
        )

    async def close(self):
        if self._client:
            await self._client.close()

    # ── Template info ─────────────────────────────────────────────

    def get_templates(self) -> list[dict]:
        """Return template metadata for UI display."""
        settings = self._settings
        result = []
        for ttype, meta in TEMPLATES.items():
            vmid = (
                settings.metasploitable3_ubuntu_vmid
                if ttype == "ubuntu"
                else settings.metasploitable3_windows_vmid
            )
            result.append({
                "type": ttype,
                "vmid": vmid,
                **meta,
            })
        return result

    # ── Capacity & allocation ─────────────────────────────────────

    async def get_capacity(self) -> dict:
        """Return current capacity info."""
        factory = _get_session_factory()
        async with factory() as session:
            active = await self._get_active_vms(session)
        return {
            "used": len(active),
            "max": self._settings.target_vm_max_concurrent,
            "available": max(0, self._settings.target_vm_max_concurrent - len(active)),
        }

    async def _get_active_vms(self, session: AsyncSession) -> list[TargetVM]:
        result = await session.execute(
            select(TargetVM).where(TargetVM.status.in_(_ACTIVE_STATUSES))
        )
        return list(result.scalars().all())

    def _allocate_ip(self, active_vms: list[TargetVM], template_type: str) -> str:
        """Allocate the next free IP address."""
        settings = self._settings
        used_ips = {vm.ip_address for vm in active_vms}

        if template_type == "windows":
            # Windows uses fixed IP at the end of the range
            ip = str(
                ipaddress.IPv4Address(settings.target_vm_ip_start)
                + settings.target_vm_ip_count - 1
            )
            if ip in used_ips:
                raise TargetLabError(
                    "A Windows target VM is already running. "
                    "Only one Windows instance is supported at a time."
                )
            return ip

        # Ubuntu: pick first free IP from range (excluding last, reserved for Windows)
        base = ipaddress.IPv4Address(settings.target_vm_ip_start)
        for i in range(settings.target_vm_ip_count - 1):
            candidate = str(base + i)
            if candidate not in used_ips:
                return candidate
        raise TargetLabError("No free IP addresses available for target VMs.")

    def _allocate_vmid(self, active_vms: list[TargetVM]) -> int:
        """Allocate the next free VMID in the target range."""
        used_vmids = {vm.vmid for vm in active_vms}
        start = self._settings.target_vm_vmid_start
        for i in range(100):
            candidate = start + i
            if candidate not in used_vmids:
                return candidate
        raise TargetLabError("No free VMIDs available for target VMs.")

    def _validate_vmid_in_range(self, vmid: int) -> None:
        """Validate VMID is within the target VM range (not a template or cluster VM)."""
        start = self._settings.target_vm_vmid_start
        end = start + 100
        if vmid < start or vmid >= end:
            raise TargetLabError(
                f"VMID {vmid} is outside target VM range ({start}-{end - 1})."
            )

    async def _find_template_node(self, template_vmid: int) -> Optional[str]:
        """Find which Proxmox node hosts a template VM.

        Templates are registered per-node even on shared storage, so we
        must check each node to find where the template config lives.
        """
        nodes = await self._client.get_nodes()
        for node in nodes:
            if await self._client.vm_exists(node, template_vmid):
                return node
        return None

    async def _select_node(self) -> str:
        """Select the Proxmox node with most resources available for deployment."""
        settings = self._settings
        if settings.target_vm_proxmox_node:
            return settings.target_vm_proxmox_node
        nodes = await self._client.get_nodes()
        if not nodes:
            raise TargetLabError("No online Proxmox nodes found.")
        factory = _get_session_factory()
        async with factory() as session:
            active = await self._get_active_vms(session)
        node_counts = {n: 0 for n in nodes}
        for vm in active:
            if vm.proxmox_node in node_counts:
                node_counts[vm.proxmox_node] += 1
        return min(node_counts, key=node_counts.get)

    # ── Deploy ────────────────────────────────────────────────────

    async def deploy_target(self, template_type: str, username: str = "admin") -> dict:
        """Deploy a new Metasploitable3 target VM.

        Uses a PostgreSQL advisory lock to prevent race conditions in
        concurrent VMID/IP allocation.
        """
        if not self.enabled:
            raise TargetLabError("Target Lab is not configured. Set PROXMOX_API_URL and PROXMOX_API_TOKEN.")

        if template_type not in TEMPLATES:
            raise TargetLabError(f"Unknown template type: {template_type}")

        settings = self._settings
        template_vmid = (
            settings.metasploitable3_ubuntu_vmid
            if template_type == "ubuntu"
            else settings.metasploitable3_windows_vmid
        )

        # Find which node hosts the template (templates are node-registered
        # even on shared storage) and select the best target node for the clone
        template_node = await self._find_template_node(template_vmid)
        if not template_node:
            raise TargetLabError(
                f"Template VMID {template_vmid} not found on any Proxmox node. "
                "Run scripts/prepare-metasploitable3-templates.sh on a Proxmox node first."
            )
        node = await self._select_node()

        factory = _get_session_factory()
        async with factory() as session:
            # Acquire advisory lock with timeout to serialize allocation
            try:
                await asyncio.wait_for(
                    session.execute(text(f"SELECT pg_advisory_lock({_ALLOCATION_LOCK_ID})")),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                raise TargetLabError("Failed to acquire deployment lock (timeout). Try again.")

            try:
                active = await self._get_active_vms(session)

                # Check capacity
                if len(active) >= settings.target_vm_max_concurrent:
                    raise TargetLabError(
                        f"Maximum concurrent target VMs reached ({settings.target_vm_max_concurrent}). "
                        "Destroy an existing VM before deploying a new one."
                    )

                # Check Windows limit
                if template_type == "windows":
                    windows_active = [v for v in active if v.template_type == "windows"]
                    max_win = TEMPLATES["windows"].get("max_instances", 1)
                    if len(windows_active) >= max_win:
                        raise TargetLabError(
                            "A Windows target VM is already running. "
                            "Only one Windows instance is supported at a time."
                        )

                # Allocate resources (safe under advisory lock)
                vmid = self._allocate_vmid(active)
                ip = self._allocate_ip(active, template_type)
                name = f"ms3-{template_type}-{vmid}"

                now = datetime.utcnow()
                ttl_expires = now + timedelta(hours=settings.target_vm_ttl_hours)

                # Remove any old destroyed/error record for this VMID
                # (unique constraint on vmid prevents reuse otherwise)
                from sqlalchemy import delete
                await session.execute(
                    delete(TargetVM).where(
                        and_(
                            TargetVM.vmid == vmid,
                            ~TargetVM.status.in_(_ACTIVE_STATUSES),
                        )
                    )
                )

                # Create DB record
                target = TargetVM(
                    vmid=vmid,
                    name=name,
                    template_type=template_type,
                    ip_address=ip,
                    proxmox_node=node,
                    status="deploying",
                    created_at=now,
                    ttl_expires_at=ttl_expires,
                    created_by=username,
                )
                session.add(target)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    raise TargetLabError(
                        f"Resource allocation conflict (VMID {vmid}). Please retry."
                    )

                # Create background task INSIDE the lock so the DB record is
                # committed before any concurrent request can re-allocate
                task = asyncio.create_task(
                    self._deploy_vm_with_timeout(vmid, template_vmid, name, node, ip, template_type, template_node)
                )
                task.add_done_callback(self._task_done_callback)
            finally:
                await session.execute(text(f"SELECT pg_advisory_unlock({_ALLOCATION_LOCK_ID})"))

        return {
            "vmid": vmid,
            "name": name,
            "template_type": template_type,
            "ip_address": ip,
            "proxmox_node": node,
            "status": "deploying",
            "ttl_expires_at": ttl_expires.isoformat(),
        }

    @staticmethod
    def _task_done_callback(task: asyncio.Task):
        """Log unhandled exceptions from background deploy tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Background deploy task failed: %s", exc)

    async def _deploy_vm_with_timeout(self, *args):
        """Wrap _deploy_vm with an overall timeout."""
        try:
            await asyncio.wait_for(self._deploy_vm(*args), timeout=600)
        except asyncio.TimeoutError:
            vmid = args[0]
            logger.error("Deploy timed out for VM %d after 600s", vmid)
            await self._update_status(vmid, "error", "Deployment timed out after 10 minutes")
            try:
                await self._client.destroy_vm(args[3], vmid)  # args[3] = node
            except Exception:
                pass

    async def _deploy_vm(
        self, vmid: int, template_vmid: int, name: str,
        node: str, ip: str, template_type: str,
        template_node: str = "",
    ):
        """Background task: clone, configure, apply firewall, start, and wait for IP."""
        settings = self._settings
        src_node = template_node or node
        try:
            # Clone template (from template's node, targeting deployment node)
            await self._client.clone_template(src_node, template_vmid, vmid, name, target_node=node)

            # Apply firewall rules to isolate the vulnerable VM (fatal if fails)
            await self._apply_vm_firewall(node, vmid)

            # Configure cloud-init IP (Ubuntu only — Windows lacks cloud-init,
            # uses fixed IP baked into template via SYSPREP or DHCP reservation)
            if template_type == "ubuntu":
                await self._client.configure_vm(
                    node, vmid, ip, settings.target_vm_gateway, settings.target_vm_netmask
                )

            # Start VM
            await self._client.start_vm(node, vmid)

            # Wait for VM to be reachable
            detected_ip = await self._client.wait_for_ip(node, vmid, timeout=180)
            if detected_ip and detected_ip != ip:
                # Validate detected IP is within the target VM range
                base = ipaddress.IPv4Address(settings.target_vm_ip_start)
                end = base + settings.target_vm_ip_count
                detected_addr = ipaddress.IPv4Address(detected_ip)
                if not (base <= detected_addr < end):
                    logger.error(
                        "VM %d: detected IP %s outside target range %s-%s",
                        vmid, detected_ip, base, end - 1,
                    )
                    raise TargetLabError(
                        f"VM got IP {detected_ip} outside allowed range"
                    )
                logger.info(
                    "VM %d: expected IP %s, detected %s (using detected)",
                    vmid, ip, detected_ip,
                )
                factory = _get_session_factory()
                async with factory() as session:
                    result = await session.execute(
                        select(TargetVM).where(TargetVM.vmid == vmid)
                    )
                    target = result.scalar_one_or_none()
                    if target:
                        target.ip_address = detected_ip
                        await session.commit()

            # Update status to running
            await self._update_status(vmid, "running")
            logger.info("Target VM %d (%s) deployed at %s", vmid, name, ip)

        except Exception as e:
            logger.error("Failed to deploy target VM %d: %s", vmid, e)
            await self._update_status(vmid, "error", str(e))
            # Attempt cleanup
            try:
                await self._client.destroy_vm(node, vmid)
            except Exception:
                pass

    async def _apply_vm_firewall(self, node: str, vmid: int):
        """Apply Proxmox firewall rules to isolate the target VM.

        Rules:
        - Allow inbound from cluster VLAN (for scanning tools to reach the VM)
        - Block all outbound except DNS (prevent pivot attacks from vulnerable VMs)
        """
        try:
            # Enable firewall on the VM
            await self._client._put(
                f"/nodes/{node}/qemu/{vmid}/firewall/options",
                data={"enable": 1, "policy_in": "ACCEPT", "policy_out": "DROP"},
            )

            # Rule 1: Allow outbound DNS (UDP 53) so services can resolve
            await self._client._post(
                f"/nodes/{node}/qemu/{vmid}/firewall/rules",
                data={
                    "type": "out", "action": "ACCEPT",
                    "proto": "udp", "dport": "53",
                    "comment": "Allow DNS resolution",
                    "enable": 1,
                },
            )

            # Rule 2: Block outbound to Proxmox management VLAN
            await self._client._post(
                f"/nodes/{node}/qemu/{vmid}/firewall/rules",
                data={
                    "type": "out", "action": "DROP",
                    "dest": "10.83.2.0/24",
                    "comment": "Block access to Proxmox management",
                    "enable": 1,
                },
            )

            # Rule 3: Block outbound to internet (0.0.0.0/0)
            # The default policy_out=DROP handles this, but explicit rule for clarity
            await self._client._post(
                f"/nodes/{node}/qemu/{vmid}/firewall/rules",
                data={
                    "type": "out", "action": "DROP",
                    "dest": "0.0.0.0/0",
                    "comment": "Block internet access from vulnerable VM",
                    "enable": 1,
                },
            )

            logger.info("Firewall rules applied to VM %d", vmid)
        except ProxmoxError as e:
            logger.error("Failed to apply firewall rules to VM %d: %s", vmid, e)
            raise  # Firewall isolation is mandatory — fail deployment

    # ── Destroy ───────────────────────────────────────────────────

    async def destroy_target(self, vmid: int, username: str = "admin") -> dict:
        """Destroy a target VM."""
        if not self.enabled:
            raise TargetLabError("Target Lab is not configured.")

        # Validate VMID is in target range (defense-in-depth)
        self._validate_vmid_in_range(vmid)

        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(TargetVM).where(
                    and_(TargetVM.vmid == vmid, TargetVM.status.in_(_ACTIVE_STATUSES))
                )
            )
            target = result.scalar_one_or_none()
            if not target:
                raise TargetLabError(f"No active target VM with VMID {vmid}.")

            target.status = "stopping"
            await session.commit()
            node = target.proxmox_node

        # Destroy on Proxmox — try the recorded node first, then search all nodes
        destroyed = False
        for try_node in [node] + [n for n in await self._client.get_nodes() if n != node]:
            try:
                if await self._client.vm_exists(try_node, vmid):
                    await self._client.destroy_vm(try_node, vmid)
                    destroyed = True
                    break
            except ProxmoxError as e:
                logger.debug("Destroy VM %d on %s failed: %s", vmid, try_node, e)
        if not destroyed:
            logger.info("VM %d not found on any Proxmox node (already removed?)", vmid)

        await self._update_status(vmid, "destroyed")

        return {"vmid": vmid, "status": "destroyed"}

    # ── TTL extension ─────────────────────────────────────────────

    async def extend_ttl(self, vmid: int, hours: int = 4, username: str = "admin") -> dict:
        """Extend the TTL of a running target VM (max 24h from creation)."""
        self._validate_vmid_in_range(vmid)
        if hours < 1 or hours > 24:
            raise TargetLabError("TTL extension must be between 1 and 24 hours.")
        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(TargetVM).where(
                    and_(TargetVM.vmid == vmid, TargetVM.status == "running")
                )
            )
            target = result.scalar_one_or_none()
            if not target:
                raise TargetLabError(f"No running target VM with VMID {vmid}.")

            new_ttl = datetime.utcnow() + timedelta(hours=hours)
            # Cap total lifetime at 24 hours from creation
            max_ttl = target.created_at + timedelta(hours=24) if target.created_at else new_ttl
            target.ttl_expires_at = min(new_ttl, max_ttl)
            await session.commit()
            return self._vm_to_dict(target)

    # ── List & status ─────────────────────────────────────────────

    async def list_targets(self) -> list[dict]:
        """Return all active target VMs."""
        factory = _get_session_factory()
        async with factory() as session:
            active = await self._get_active_vms(session)
            return [self._vm_to_dict(vm) for vm in active]

    async def get_target(self, vmid: int) -> Optional[dict]:
        """Get a single target VM by VMID."""
        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(TargetVM).where(TargetVM.vmid == vmid)
            )
            target = result.scalar_one_or_none()
            if not target:
                return None
            return self._vm_to_dict(target)

    # ── TTL cleanup ───────────────────────────────────────────────

    async def cleanup_expired(self):
        """Destroy VMs that have exceeded their TTL."""
        now = datetime.utcnow()
        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(TargetVM).where(
                    and_(
                        TargetVM.status.in_(_ACTIVE_STATUSES),
                        TargetVM.ttl_expires_at <= now,
                    )
                )
            )
            expired = list(result.scalars().all())

        if not expired:
            return

        logger.info("TTL cleanup: destroying %d expired target VM(s)", len(expired))
        for vm in expired:
            try:
                await self.destroy_target(vm.vmid, username="system-ttl")
            except Exception as e:
                logger.error("TTL cleanup failed for VM %d: %s", vm.vmid, e)

    async def reconcile_orphaned(self):
        """Clean up VMs stuck in 'deploying' or 'error' state.

        - VMs in 'deploying' for >30 min: mark as error and destroy on Proxmox
        - VMs in 'error' for >10 min: attempt destroy on Proxmox and mark destroyed
        """
        now = datetime.utcnow()
        deploy_cutoff = now - timedelta(minutes=30)
        error_cutoff = now - timedelta(minutes=10)
        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(TargetVM).where(
                    and_(
                        TargetVM.status == "deploying",
                        TargetVM.created_at <= deploy_cutoff,
                    )
                )
            )
            orphaned = list(result.scalars().all())

            # Also find stale error VMs to clean up from Proxmox
            result2 = await session.execute(
                select(TargetVM).where(
                    and_(
                        TargetVM.status == "error",
                        TargetVM.created_at <= error_cutoff,
                    )
                )
            )
            stale_errors = list(result2.scalars().all())

        for vm in orphaned:
            logger.warning("Reconciling orphaned VM %d (deploying since %s)", vm.vmid, vm.created_at)
            await self._update_status(vm.vmid, "error", "Deployment timed out (orphan reconciliation)")
            try:
                if self._client:
                    await self._client.destroy_vm(vm.proxmox_node, vm.vmid)
            except Exception:
                pass

        for vm in stale_errors:
            logger.info("Cleaning up error VM %d from Proxmox", vm.vmid)
            try:
                if self._client:
                    await self._client.destroy_vm(vm.proxmox_node, vm.vmid)
            except Exception:
                pass
            await self._update_status(vm.vmid, "destroyed")

    # ── Helpers ───────────────────────────────────────────────────

    async def _update_status(
        self, vmid: int, status: str, error: str = None
    ):
        factory = _get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(TargetVM).where(TargetVM.vmid == vmid)
            )
            target = result.scalar_one_or_none()
            if target:
                target.status = status
                if error:
                    target.error_message = error
                if status == "destroyed":
                    target.destroyed_at = datetime.utcnow()
                await session.commit()

    @staticmethod
    def _vm_to_dict(vm: TargetVM) -> dict:
        now = datetime.utcnow()
        return {
            "vmid": vm.vmid,
            "name": vm.name,
            "template_type": vm.template_type,
            "ip_address": vm.ip_address,
            "proxmox_node": vm.proxmox_node,
            "status": vm.status,
            "created_at": vm.created_at.isoformat() if vm.created_at else None,
            "ttl_expires_at": vm.ttl_expires_at.isoformat() if vm.ttl_expires_at else None,
            "ttl_remaining_seconds": max(0, int((vm.ttl_expires_at - now).total_seconds())) if vm.ttl_expires_at else 0,
            "created_by": vm.created_by,
            "error_message": vm.error_message,
            "template_info": TEMPLATES.get(vm.template_type, {}),
        }


# ── Singleton ─────────────────────────────────────────────────────

_target_lab_service: Optional[TargetLabService] = None


def get_target_lab_service() -> TargetLabService:
    global _target_lab_service
    if _target_lab_service is None:
        _target_lab_service = TargetLabService()
    return _target_lab_service

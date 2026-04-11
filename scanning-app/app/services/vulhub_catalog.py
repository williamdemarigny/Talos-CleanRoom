"""Static catalog of curated Vulhub vulnerable environments.

Each entry maps an env_id to metadata used by VulhubTargetService for
deployment and by the UI for display.  The ``manifest`` field references
a YAML file baked into the container image at /app/vulhub-manifests/.

Categories: rce, tls, web, auth, sqli, network, dns.

Tiers control resource allocation:
  tier1 — Lightweight single container (250m CPU / 256Mi)
  tier2 — Standard single container  (500m CPU / 512Mi)
  tier3 — Multi-container pods        (500m CPU / 512Mi per container, higher quota)
"""

from typing import Optional

# ── Tier definitions ─────────────────────────────────────────────

TIER_CONFIG: dict[str, dict] = {
    "tier1": {
        "label": "Lightweight",
        "cpu_request": "50m",
        "cpu_limit": "250m",
        "memory_request": "64Mi",
        "memory_limit": "256Mi",
        "max_pods": 2,
        "rollout_timeout": 180,
        "badge_color": "green",
    },
    "tier2": {
        "label": "Standard",
        "cpu_request": "100m",
        "cpu_limit": "500m",
        "memory_request": "128Mi",
        "memory_limit": "512Mi",
        "max_pods": 3,
        "rollout_timeout": 300,
        "badge_color": "blue",
    },
    "tier3": {
        "label": "Multi-container",
        "cpu_request": "100m",
        "cpu_limit": "500m",
        "memory_request": "128Mi",
        "memory_limit": "512Mi",
        "max_pods": 5,
        "rollout_timeout": 300,
        "badge_color": "purple",
    },
}

# ── Vulhub environment catalog ──────────────────────────────────

VULHUB_CATALOG: dict[str, dict] = {

    # ── RCE ───────────────────────────────────────────────────────
    "log4shell": {
        "name": "Log4Shell (CVE-2021-44228)",
        "cve": "CVE-2021-44228",
        "category": "rce",
        "description": "Apache Log4j2 JNDI RCE — the most impactful CVE of 2021",
        "services": ["Solr (8983)"],
        "ports": [8983],
        "images": ["vulhub/solr:8.11.0"],
        "manifest": "log4shell.yaml",
        "difficulty": "easy",
        "tier": "tier2",
        "recommended_scan": {
            "tools": ["nmap", "metasploit"],
            "profile": "standard",
        },
    },
    # ── TLS ───────────────────────────────────────────────────────
    "heartbleed": {
        "name": "Heartbleed (CVE-2014-0160)",
        "cve": "CVE-2014-0160",
        "category": "tls",
        "description": "OpenSSL TLS heartbeat extension information leak",
        "services": ["Nginx/HTTPS (8443)"],
        "ports": [8443],
        "images": ["vulhub/openssl:1.0.1c-with-nginx"],
        "manifest": "heartbleed.yaml",
        "difficulty": "easy",
        "tier": "tier1",
        "recommended_scan": {
            "tools": ["nmap", "openvas"],
            "profile": "standard",
            "nmap_scripts": "ssl-heartbleed,ssl-enum-ciphers,ssl-cert",
        },
    },

    # ── Web ───────────────────────────────────────────────────────
    "struts2-s2045": {
        "name": "Struts2 S2-045 (CVE-2017-5638)",
        "cve": "CVE-2017-5638",
        "category": "web",
        "description": "Apache Struts2 Jakarta Multipart parser RCE (Equifax breach vector)",
        "services": ["Struts2 App (8080)"],
        "ports": [8080],
        "images": ["vulhub/struts2:2.3.30"],
        "manifest": "struts2-s2045.yaml",
        "difficulty": "easy",
        "tier": "tier2",
        "recommended_scan": {
            "tools": ["nmap", "openvas"],
            "profile": "standard",
            "nmap_scripts": "http-vuln-cve2017-5638",
        },
    },
    # ── Auth ──────────────────────────────────────────────────────
    "libssh-auth-bypass": {
        "name": "libssh Auth Bypass (CVE-2018-10933)",
        "cve": "CVE-2018-10933",
        "category": "auth",
        "description": "libssh server-side authentication bypass",
        "services": ["SSH (2222)"],
        "ports": [2222],
        "images": ["vulhub/libssh:0.8.1"],
        "manifest": "libssh-auth-bypass.yaml",
        "difficulty": "easy",
        "tier": "tier1",
        "recommended_scan": {
            "tools": ["nmap", "metasploit"],
            "profile": "custom",
            "nmap_scripts": "ssh2-enum-algos,sshv1",
            "msf_modules": [
                "auxiliary/scanner/ssh/libssh_auth_bypass",
                "auxiliary/scanner/ssh/ssh_version",
            ],
        },
    },

    # ── SQLi ──────────────────────────────────────────────────────
    "mysql-auth-bypass": {
        "name": "MySQL Auth Bypass (CVE-2012-2122)",
        "cve": "CVE-2012-2122",
        "category": "sqli",
        "description": "MySQL/MariaDB authentication bypass via timing attack",
        "services": ["MySQL (3306)"],
        "ports": [3306],
        "images": ["vulhub/mysql:5.5.23"],
        "manifest": "mysql-auth-bypass.yaml",
        "difficulty": "easy",
        "tier": "tier1",
        "recommended_scan": {
            "tools": ["nmap", "metasploit"],
            "profile": "custom",
            "nmap_scripts": "mysql-vuln-cve2012-2122,mysql-info,mysql-enum",
            "msf_modules": [
                "auxiliary/scanner/mysql/mysql_authbypass_hashdump",
                "auxiliary/scanner/mysql/mysql_version",
            ],
        },
    },

    # ── Network ───────────────────────────────────────────────────
    "sambacry": {
        "name": "SambaCry (CVE-2017-7494)",
        "cve": "CVE-2017-7494",
        "category": "network",
        "description": "Samba remote code execution via writable share",
        "services": ["Samba (445)"],
        "ports": [445],
        "images": ["vulhub/samba:4.6.3"],
        "manifest": "sambacry.yaml",
        "difficulty": "medium",
        "tier": "tier2",
        "recommended_scan": {
            "tools": ["nmap", "metasploit"],
            "profile": "standard",
            "nmap_scripts": "smb-os-discovery,smb-protocols,smb-vuln-*",
            "msf_modules": [
                "exploit/linux/samba/is_known_pipename",
                "auxiliary/scanner/smb/smb_ms17_010",
                "auxiliary/scanner/smb/smb_version",
                "auxiliary/scanner/smb/smb_enumshares",
                "auxiliary/scanner/smb/pipe_auditor",
            ],
        },
    },
    "redis-unauth": {
        "name": "Redis Unauthorized Access",
        "cve": None,
        "category": "network",
        "description": "Redis server with no authentication — arbitrary file write",
        "services": ["Redis (6379)"],
        "ports": [6379],
        "images": ["vulhub/redis:5.0.7"],
        "manifest": "redis-unauth.yaml",
        "difficulty": "easy",
        "tier": "tier1",
        "recommended_scan": {
            "tools": ["nmap", "metasploit"],
            "profile": "thorough",
            "msf_modules": ["auxiliary/scanner/redis/redis_server"],
        },
    },

    # ── DNS ───────────────────────────────────────────────────────
    "bind9-tsig": {
        "name": "BIND9 TSIG (CVE-2017-3143)",
        "cve": "CVE-2017-3143",
        "category": "dns",
        "description": "BIND9 TSIG authentication bypass for zone updates",
        "services": ["BIND9 DNS (53)"],
        "ports": [53],
        "images": ["vulhub/bind:9.10.3"],
        "manifest": "bind9-tsig.yaml",
        "difficulty": "medium",
        "tier": "tier1",
        "recommended_scan": {
            "tools": ["nmap"],
            "profile": "standard",
            # vulners triggers when nmap version detection identifies BIND 9.10.x
            # which is vulnerable to CVE-2017-3143
            "nmap_scripts": "vulners,dns-nsid,dns-recursion",
        },
    },

}


def get_catalog(category: Optional[str] = None) -> dict[str, dict]:
    """Return the catalog, optionally filtered by category.

    Args:
        category: If provided, only return entries matching this category.

    Returns:
        Dict mapping env_id to metadata for matching environments.
    """
    if category is None:
        return dict(VULHUB_CATALOG)
    return {
        env_id: entry
        for env_id, entry in VULHUB_CATALOG.items()
        if entry["category"] == category
    }

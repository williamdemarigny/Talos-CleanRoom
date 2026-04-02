"""Static catalog of curated Vulhub vulnerable environments.

Each entry maps an env_id to metadata used by VulhubTargetService for
deployment and by the UI for display.  The ``manifest`` field references
a YAML file baked into the container image at /app/vulhub-manifests/.

Categories: rce, tls, web, auth, ssrf, xxe, sqli, nosql, network, dns,
php, misc, container.
"""

from typing import Optional

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
    },
    "spring4shell": {
        "name": "Spring4Shell (CVE-2022-22965)",
        "cve": "CVE-2022-22965",
        "category": "rce",
        "description": "Spring Framework parameter binding RCE via ClassLoader manipulation",
        "services": ["Spring App (8080)"],
        "ports": [8080],
        "images": ["vulhub/spring-core:5.3.17"],
        "manifest": "spring4shell.yaml",
        "difficulty": "easy",
    },

    # ── TLS ───────────────────────────────────────────────────────
    "heartbleed": {
        "name": "Heartbleed (CVE-2014-0160)",
        "cve": "CVE-2014-0160",
        "category": "tls",
        "description": "OpenSSL TLS heartbeat extension information leak",
        "services": ["Nginx/HTTPS (8443)"],
        "ports": [8443],
        "images": ["vulhub/openssl:1.0.1f-nginx"],
        "manifest": "heartbleed.yaml",
        "difficulty": "easy",
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
    },
    "drupalgeddon2": {
        "name": "Drupalgeddon 2 (CVE-2018-7600)",
        "cve": "CVE-2018-7600",
        "category": "web",
        "description": "Drupal 7 remote code execution via Form API",
        "services": ["Drupal (80)", "MySQL (3306)"],
        "ports": [80],
        "images": ["vulhub/drupal:8.5.0", "mysql:5.7"],
        "manifest": "drupalgeddon2.yaml",
        "difficulty": "easy",
    },
    # ── Additional environments can be added here ─────────────────
    # To add a new environment:
    #   1. Create K8s manifest in apps/vulhub-targets/manifests/<name>.yaml
    #   2. Add catalog entry here with matching manifest filename
    #   3. Rebuild and push the scanning-console image
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

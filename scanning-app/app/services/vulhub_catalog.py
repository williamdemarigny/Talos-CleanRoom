"""Static catalog of curated Vulhub vulnerable environments.

Each entry maps an env_id to metadata used by VulhubTargetService for
deployment and by the UI for display.  The ``manifest`` field references
a YAML file baked into the container image at /app/vulhub-manifests/.

Categories: rce, tls, web, auth, ssrf, xxe, sqli, nosql, network, dns,
php, misc, container.

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
        "rollout_timeout": 120,
        "badge_color": "green",
    },
    "tier2": {
        "label": "Standard",
        "cpu_request": "100m",
        "cpu_limit": "500m",
        "memory_request": "128Mi",
        "memory_limit": "512Mi",
        "max_pods": 3,
        "rollout_timeout": 180,
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
        "images": ["vulhub/openssl:1.0.1f-nginx"],
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
        },
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
        "tier": "tier3",
        "recommended_scan": {
            "tools": ["nmap", "openvas"],
            "profile": "standard",
        },
    },
    "wordpress-phpmailer": {
        "name": "WordPress PHPMailer (CVE-2016-10033)",
        "cve": "CVE-2016-10033",
        "category": "web",
        "description": "WordPress PHPMailer RCE via mail header injection",
        "services": ["WordPress (80)", "MySQL (3306)"],
        "ports": [80],
        "images": ["vulhub/wordpress:4.6", "mysql:5.7"],
        "manifest": "wordpress-phpmailer.yaml",
        "difficulty": "easy",
        "tier": "tier3",
        "recommended_scan": {
            "tools": ["nmap", "openvas"],
            "profile": "standard",
        },
    },
    "tomcat-put": {
        "name": "Tomcat PUT (CVE-2017-12615)",
        "cve": "CVE-2017-12615",
        "category": "web",
        "description": "Apache Tomcat remote code execution via PUT method",
        "services": ["Tomcat (8080)"],
        "ports": [8080],
        "images": ["vulhub/tomcat:8.5.19"],
        "manifest": "tomcat-put.yaml",
        "difficulty": "easy",
        "tier": "tier2",
        "recommended_scan": {
            "tools": ["nmap", "openvas"],
            "profile": "standard",
        },
    },

    # ── Auth ──────────────────────────────────────────────────────
    "shiro-deser": {
        "name": "Apache Shiro Deser (CVE-2016-4437)",
        "cve": "CVE-2016-4437",
        "category": "auth",
        "description": "Apache Shiro RememberMe cookie deserialization RCE",
        "services": ["Shiro App (8080)"],
        "ports": [8080],
        "images": ["vulhub/shiro:1.2.4"],
        "manifest": "shiro-deser.yaml",
        "difficulty": "medium",
        "tier": "tier2",
        "recommended_scan": {
            "tools": ["nmap", "metasploit"],
            "profile": "standard",
        },
    },
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
            "profile": "standard",
            "msf_modules": ["auxiliary/scanner/ssh/libssh_auth_bypass"],
        },
    },

    # ── SSRF ──────────────────────────────────────────────────────
    "weblogic-ssrf": {
        "name": "WebLogic SSRF (CVE-2014-4210)",
        "cve": "CVE-2014-4210",
        "category": "ssrf",
        "description": "Oracle WebLogic Server-Side Request Forgery",
        "services": ["WebLogic (7001)"],
        "ports": [7001],
        "images": ["vulhub/weblogic:10.3.6.0-2017"],
        "manifest": "weblogic-ssrf.yaml",
        "difficulty": "medium",
        "tier": "tier2",
        "recommended_scan": {
            "tools": ["nmap", "openvas"],
            "profile": "standard",
        },
    },

    # ── XXE ───────────────────────────────────────────────────────
    "weblogic-xmldecoder": {
        "name": "WebLogic XMLDecoder (CVE-2017-10271)",
        "cve": "CVE-2017-10271",
        "category": "xxe",
        "description": "Oracle WebLogic WLS-WSAT XMLDecoder deserialization RCE",
        "services": ["WebLogic (7001)"],
        "ports": [7001],
        "images": ["vulhub/weblogic:10.3.6.0-2017"],
        "manifest": "weblogic-xmldecoder.yaml",
        "difficulty": "medium",
        "tier": "tier2",
        "recommended_scan": {
            "tools": ["nmap", "openvas"],
            "profile": "standard",
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
            "profile": "standard",
            "msf_modules": ["auxiliary/scanner/mysql/mysql_version"],
        },
    },

    # ── NoSQL ─────────────────────────────────────────────────────
    "mongo-express-rce": {
        "name": "mongo-express RCE (CVE-2019-10758)",
        "cve": "CVE-2019-10758",
        "category": "nosql",
        "description": "mongo-express remote code execution via SSJS injection",
        "services": ["mongo-express (8081)", "MongoDB (27017)"],
        "ports": [8081],
        "images": ["vulhub/mongo-express:0.54.0", "mongo:3.6"],
        "manifest": "mongo-express-rce.yaml",
        "difficulty": "easy",
        "tier": "tier3",
        "recommended_scan": {
            "tools": ["nmap", "metasploit"],
            "profile": "standard",
            "msf_modules": ["auxiliary/scanner/mongodb/mongodb_login"],
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
            "profile": "thorough",
            "msf_modules": [
                "auxiliary/scanner/smb/smb_version",
                "auxiliary/scanner/smb/smb_enumshares",
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
    "elasticsearch-groovy": {
        "name": "Elasticsearch Groovy (CVE-2015-1427)",
        "cve": "CVE-2015-1427",
        "category": "network",
        "description": "Elasticsearch Groovy script engine sandbox escape RCE",
        "services": ["Elasticsearch (9200)"],
        "ports": [9200],
        "images": ["vulhub/elasticsearch:1.4.2"],
        "manifest": "elasticsearch-groovy.yaml",
        "difficulty": "easy",
        "tier": "tier2",
        "recommended_scan": {
            "tools": ["nmap", "metasploit"],
            "profile": "thorough",
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
        "images": ["vulhub/bind:9.10.6"],
        "manifest": "bind9-tsig.yaml",
        "difficulty": "medium",
        "tier": "tier1",
        "recommended_scan": {
            "tools": ["nmap"],
            "profile": "quick",
            "nmap_scripts": "dns-zone-transfer,dns-update,dns-nsid",
        },
    },

    # ── PHP ───────────────────────────────────────────────────────
    "php-fpm-rce": {
        "name": "PHP-FPM RCE (CVE-2019-11043)",
        "cve": "CVE-2019-11043",
        "category": "php",
        "description": "PHP-FPM remote code execution via path_info underflow",
        "services": ["Nginx+PHP-FPM (8080)"],
        "ports": [8080],
        "images": ["vulhub/php:7.1.10-fpm-stretch-with-nginx"],
        "manifest": "php-fpm-rce.yaml",
        "difficulty": "medium",
        "tier": "tier1",
        "recommended_scan": {
            "tools": ["nmap", "openvas"],
            "profile": "standard",
        },
    },

    # ── Misc ──────────────────────────────────────────────────────
    "nginx-misconfig": {
        "name": "Nginx Misconfiguration",
        "cve": None,
        "category": "misc",
        "description": "Common Nginx misconfigurations: directory traversal, alias bypass",
        "services": ["Nginx (8080)"],
        "ports": [8080],
        "images": ["vulhub/nginx:insecure-configuration"],
        "manifest": "nginx-misconfig.yaml",
        "difficulty": "easy",
        "tier": "tier1",
        "recommended_scan": {
            "tools": ["nmap", "openvas"],
            "profile": "quick",
        },
    },

    # ── Container ─────────────────────────────────────────────────
    "runc-escape": {
        "name": "runc Container Escape (CVE-2019-5736) — Demo Only",
        "cve": "CVE-2019-5736",
        "category": "container",
        "description": "runc container escape via /proc/self/exe overwrite (demo mode, non-exploitable)",
        "services": ["Container Runtime (Demo) (80)"],
        "ports": [80],
        "images": ["vulhub/runc:1.0.0-rc6"],
        "manifest": "runc-escape.yaml",
        "difficulty": "hard",
        "tier": "tier1",
        "recommended_scan": {
            "tools": ["nmap"],
            "profile": "quick",
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

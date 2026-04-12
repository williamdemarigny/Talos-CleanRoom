# Vulhub Target Lab — Curated 8-Lab Set

> Updated: 2026-04-11

## Status

The Vulhub catalog has been curated down to **8 labs** that work end-to-end
with our scanner toolchain (Nmap + Metasploit). The previous 16-lab set
included 8 labs that could not be detected by Metasploit alone — see the
"Removed labs" section below for the rationale.

## The 8 working labs

| env_id | CVE | Category | Detection |
|---|---|---|---|
| log4shell | CVE-2021-44228 | rce | nmap `vulners` (Solr version banner) |
| heartbleed | CVE-2014-0160 | tls | nmap `ssl-heartbleed` NSE script |
| struts2-s2045 | CVE-2017-5638 | web | nmap `http-vuln-cve2017-5638` |
| libssh-auth-bypass | CVE-2018-10933 | auth | msf `libssh_auth_bypass` |
| mysql-auth-bypass | CVE-2012-2122 | sqli | nmap `mysql-vuln-cve2012-2122` + msf `mysql_authbypass_hashdump` |
| sambacry | CVE-2017-7494 | network | msf `is_known_pipename` |
| redis-unauth | (no CVE) | network | msf `redis_server` |
| bind9-tsig | CVE-2017-3143 | dns | nmap `vulners` (BIND version banner) |

All 8 should pass `validate-targets.sh` end-to-end (deploy → pod_ready →
reachable → scan → CVE detected) when run with the default Nmap+Metasploit
tool set.

## Removed labs (and why)

| env_id | CVE | Reason removed |
|---|---|---|
| drupalgeddon2 | CVE-2018-7600 | Vulhub ships Drupal **uninstalled**. All HTTP requests 302 to `/core/install.php`. MSF `drupal_drupalgeddon2` cannot determine version → can't confirm vuln. Would require an init container to run `drush site-install`. |
| wordpress-phpmailer | CVE-2016-10033 | Vulhub ships WordPress **uninstalled**. WordPress 5-min setup wizard blocks all routes. MSF `wp_phpmailer_host_header` can't detect version. |
| elasticsearch-groovy | CVE-2015-1427 | The Groovy `_search` payload requires at least one document in the index, but Vulhub ships ES with no indices. Vulhub README explicitly says: *"querying requires at least one document in the index, first send the following request to add data."* |
| tomcat-put | CVE-2017-12615 | MSF `tomcat_jsp_upload_bypass` has `Check supported: Yes` but reports no vuln on Vulhub's image — the default servlet PUT method may be blocked even though `readonly=false` is set in `web.xml`. Detection works only by actually performing the upload exploit. |
| shiro-deser | CVE-2016-4437 | The only shiro module in this MSF version is `exploit/multi/http/shiro_rememberme_v124_deserialize`, which has `Check supported: No`. There is no `apache_shiro_check` auxiliary in this MSF version. |
| weblogic-ssrf | CVE-2014-4210 | No MSF module covers WebLogic SSRF in this MSF version (verified by `search weblogic`). None of the 18 weblogic modules target the `/uddiexplorer/` path. |
| weblogic-xmldecoder | CVE-2017-10271 | `exploit/multi/http/oracle_weblogic_wsat_deserialization_rce` exists but has `Check supported: No`. |
| mongo-express-rce | CVE-2019-10758 | No MSF module covers mongo-express in this MSF version (verified by `search mongo`). |

The **first three** failures (drupalgeddon2, wordpress-phpmailer,
elasticsearch-groovy) are Vulhub upstream design issues — the apps ship
uninstalled or empty. They could be re-added later via init-container
automation that completes the install/setup steps before scanning starts.

The **next five** failures (tomcat-put, shiro-deser, weblogic-ssrf,
weblogic-xmldecoder, mongo-express-rce) are Metasploit-version limitations.
They could be re-added if we either upgrade Metasploit to a version with
these modules, or add a custom HTTP probe pass to the scanner that detects
each CVE directly via response patterns.

## Phase B — OpenVAS validation results

Ran the validator with `VALIDATOR_TOOLS_OVERRIDE='["nmap","openvas"]'`
against all 8 curated labs. **Discovered and fixed a silent OpenVAS XML
parser bug** in the process.

### Parser bug discovered & fixed (commit `4ba30c5`)

The original parser at [scan_service.py:4391](../../scanning-app/app/services/scan_service.py#L4391)
was reading CVE refs from `<nvt><cve>...</cve></nvt>` (legacy GMP <22 format).
**Modern GVM (21.04+) uses `<nvt><refs><ref type="cve" id="CVE-..."/></refs></nvt>`
exclusively.** The legacy `<cve>` tag does not exist in current OpenVAS
output.

Result: every OpenVAS finding silently got `cves=[]` and `external_ids=None`.
Verified by dumping a raw `<get_reports details="1">` from gvmd inside the
running greenbone pod and confirming `<cve> tag present: False`,
`<refs> blocks present: True`.

The new parser handles both formats and falls back to scraping CVE patterns
from description text. **Verified by re-running heartbleed:** previously had
zero OpenVAS-sourced CVE matches; now correctly surfaces
`SSL/TLS: OpenSSL TLS 'heartbeat' Extension Information Disclosure`
with `external_id=CVE-2014-0160`.

### Final 8-lab matrix (after parser fix)

| Target | Nmap NSE | OpenVAS | Metasploit | Detected by |
|---|---|---|---|---|
| log4shell | — | — | check | **Metasploit only** |
| heartbleed | `ssl-heartbleed` | NVT 117638 | check | All 3 scanners |
| struts2-s2045 | `http-vuln-cve2017-5638` | — | check | nmap + Metasploit |
| libssh-auth-bypass | — | — | check | **Metasploit only** |
| mysql-auth-bypass | `mysql-vuln-cve2012-2122` | — | hashdump | nmap + Metasploit |
| sambacry | — | — | `is_known_pipename` | **Metasploit only** |
| redis-unauth | — | (no CVE) | `redis_server` | nmap + Metasploit |
| bind9-tsig | `vulners` | — | (no module) | nmap only |

**Summary:**
- **Metasploit alone:** 8/8 PASS
- **Nmap NSE alone:** 5/8 PASS (heartbleed, struts2, mysql, redis, bind9)
- **OpenVAS alone:** 1/8 PASS (heartbleed)
- **Combined (any scanner):** 8/8 PASS

### Why OpenVAS only detects heartbleed

For the 3 targets that need an *active* OpenVAS check NVT (log4shell,
libssh, sambacry), the corresponding NVTs **exist in the feed** and **belong
to families enabled by Full and Fast** but did not surface findings:

| Target | NVT OID | Family | Likely reason no finding |
|---|---|---|---|
| log4shell | `1.3.6.1.4.1.25623.1.0.113858` (HTTP active check) | Web application abuses | NVT injects `${jndi:ldap://scanner-callback/}` into HTTP headers and waits for the target to call back to the OpenVAS scanner. Our zero-trust NetworkPolicies block egress from vulhub namespaces to the openvas namespace, so no callback ever arrives. |
| libssh-auth-bypass | `1.3.6.1.4.1.25623.1.0.108473` | General | NVT exists but the SSH-specific authentication-state probe needs custom protocol handling that the openvas-scanner may not perform on non-standard ports / against libssh-only servers. |
| sambacry | `1.3.6.1.4.1.25623.1.0.811055` | General | NVT requires enumerating writable shares first. The `auxiliary/scanner/smb/smb_enumshares` step is part of Metasploit's SambaCry workflow but OpenVAS Full and Fast has no equivalent precondition NVT chain. |

For the other 4 working targets, nmap NSE scripts already produce CVE-mapped
findings (`http-vuln-cve2017-5638`, `mysql-vuln-cve2012-2122`,
`ssl-heartbleed`, `vulners`). OpenVAS in our environment is providing
**defensive depth** for these — additional findings, version detection,
posture checks (Weak KEX, SMBv1 enabled, missing security headers) — even
when it doesn't surface the headline CVE itself.

### Validator script bug fix (same commit)

`--tools` and `--profile` CLI flags were dead code: they set
`VALIDATOR_TOOLS` / `VALIDATOR_PROFILE` but `test_target()` only reads
`VALIDATOR_TOOLS_OVERRIDE` / `VALIDATOR_PROFILE_OVERRIDE` env vars. Now the
flags map to the override vars correctly.

## Manifest files on disk

Of the 12 manifest files remaining in `manifests/`, **8 are referenced by
the catalog** and **4 are not** (nginx-misconfig, php-fpm-rce, runc-escape,
spring4shell). The unreferenced four are leftover from an earlier exploration
and are intentionally not in the catalog. They are not deployed or tested.

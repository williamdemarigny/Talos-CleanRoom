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

## Phase B — OpenVAS validation against the 8 working labs

After this curation, the next step is to run focused OpenVAS scans against
each of the 8 working labs to confirm OpenVAS NVTs detect the same CVEs
that Nmap/Metasploit do. Use:

```bash
SCANNING_PW=... ./validate-targets.sh \
  --tools '["nmap","openvas"]' --scan-timeout 60
```

(OpenVAS scans take 15-45 min each so a full run is 2-6 hours.)

## Manifest files on disk

Of the 12 manifest files remaining in `manifests/`, **8 are referenced by
the catalog** and **4 are not** (nginx-misconfig, php-fpm-rce, runc-escape,
spring4shell). The unreferenced four are leftover from an earlier exploration
and are intentionally not in the catalog. They are not deployed or tested.

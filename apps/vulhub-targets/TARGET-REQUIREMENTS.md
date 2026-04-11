# Vulhub Target Lab Requirements & Detection Status

> Per-target analysis of why each lab passes or fails the validator (`validate-targets.sh`).
> Updated: 2026-04-11.

## Summary

After three validator runs and per-target investigation, the 16 Vulhub labs fall
into four buckets:

| Bucket | Count | Targets |
|---|---|---|
| **PASS** — vulnerable as deployed, MSF check works | 8 | log4shell, struts2-s2045, mysql-auth-bypass, sambacry, redis-unauth, libssh-auth-bypass, heartbleed, bind9-tsig |
| **FAIL — Vulhub upstream design** (app ships uninstalled / requires data setup) | 3 | drupalgeddon2, wordpress-phpmailer, elasticsearch-groovy |
| **FAIL — missing MSF module in catalog** | 3 | shiro-deser, weblogic-ssrf, mongo-express-rce |
| **FAIL — module exists but check fails (needs investigation)** | 2 | tomcat-put, weblogic-xmldecoder |

## Per-target detail

### Pass

| Target | CVE | Detection method |
|---|---|---|
| log4shell | CVE-2021-44228 | `vulners` (Solr version banner) |
| struts2-s2045 | CVE-2017-5638 | `http-vuln-cve2017-5638` NSE script |
| mysql-auth-bypass | CVE-2012-2122 | `mysql-vuln-cve2012-2122` NSE + `mysql_authbypass_hashdump` |
| sambacry | CVE-2017-7494 | `is_known_pipename` MSF check |
| redis-unauth | (none) | `redis_server` MSF auxiliary |
| libssh-auth-bypass | CVE-2018-10933 | `libssh_auth_bypass` MSF check |
| heartbleed | CVE-2014-0160 | `ssl-heartbleed` NSE script |
| bind9-tsig | CVE-2017-3143 | `vulners` (BIND version banner) |

### Fail — Vulhub upstream design (app needs manual setup)

These labs ship with the application **uninstalled** or **empty**. The
vulnerability exists in the binary, but the running service redirects all
requests to a setup wizard or returns errors until a human completes setup.
MSF `check` methods cannot determine the version → cannot confirm vuln.

| Target | CVE | Required setup | Source |
|---|---|---|---|
| drupalgeddon2 | CVE-2018-7600 | Run Drupal install wizard at `/core/install.php` (database, admin user, site config) | Vulhub README: "Complete the drupal installation using the standard profile" |
| wordpress-phpmailer | CVE-2016-10033 | Run WordPress 5-minute install (admin user, site title) | Vulhub README mentions WP setup wizard |
| elasticsearch-groovy | CVE-2015-1427 | `POST /website/blog/ {"name":"test"}` to create at least one document so the Groovy `_search` payload has something to query | Vulhub README: "querying requires at least one document in the index, first send the following request to add data" |

**Fix path:** add init containers or post-deploy `Job` to bootstrap each app
(see Phase C below).

### Fail — missing MSF module in catalog

`MSF_MODULE_CATALOG` in `scanning-app/app/services/scan_service.py` does not
include any check module that handles these CVEs. The catalog file
(`vulhub_catalog.py`) lists `msf_modules` but that field is **informational
only** — the real list of modules to run comes from `MSF_MODULE_CATALOG`
filtered by profile.

| Target | CVE | Module to add | Notes |
|---|---|---|---|
| shiro-deser | CVE-2016-4437 | `auxiliary/scanner/http/apache_shiro_check` | Detects vulnerable RememberMe cookie handling. Default creds `admin:vulhub` not needed for check. |
| weblogic-ssrf | CVE-2014-4210 | `auxiliary/scanner/http/oracle_weblogic_ssrf` | Probes `/uddiexplorer/SearchPublicRegistries.jsp` |
| mongo-express-rce | CVE-2019-10758 | `exploit/linux/http/mongo_express_rce` | Default creds `admin:pass` (set in module options) |

**Fix path:** add 3 entries to `MSF_MODULE_CATALOG` under the "Vulhub Labs"
section, profile `["standard","thorough"]`, then rebuild the scanning-console
image.

### Fail — module exists but check fails (needs further investigation)

These have MSF modules already in the catalog. The `check` method runs but
returns `Unknown` or `Safe` instead of `Vulnerable`/`Detected`.

| Target | CVE | Module currently used | Hypothesis |
|---|---|---|---|
| tomcat-put | CVE-2017-12615 | `exploit/multi/http/tomcat_jsp_upload_bypass` | Module may PUT a real test file; if WAF/auth blocks PUT it cannot confirm. Manual `kubectl exec` test needed. |
| weblogic-xmldecoder | CVE-2017-10271 | `exploit/multi/http/oracle_weblogic_wsat_deserialization_rce` | WebLogic 7001 takes 60-90s to fully start; MSF check may run before WLS is ready. May also need patched check method. |

**Fix path:** manual probe with `kubectl exec` from a metasploit pod, then
either swap modules or add an Nmap NSE script (`http-vuln-cve2017-12615`,
`http-vuln-cve2017-10271`) as fallback.

## Action items

### Phase A (this doc) — DONE
Investigate all 8 failing targets, classify root cause.

### Phase B — Focused OpenVAS validation
Run `validate-targets.sh` with `VALIDATOR_TOOLS_OVERRIDE='["nmap","openvas"]'`
against each of the 8 failing targets one at a time. OpenVAS can detect
version-based CVEs from server banners alone (no auth, no install needed),
so it should pass several of these labs that MSF cannot — particularly the
WebLogic ones and possibly the uninstalled Drupal/WordPress (server header
shows `Apache` + PHP version).

### Phase C — Init-container automation
Add bootstrap automation for the 3 "needs setup" labs:

| Lab | Bootstrap action |
|---|---|
| drupalgeddon2 | Init container runs `drush site-install` against MySQL with default profile |
| wordpress-phpmailer | Init container `curl -d` to `/wp-admin/install.php?step=2` with admin user/pass/title |
| elasticsearch-groovy | Init container waits for ES on 9200, then `curl -XPUT /website/blog/1 -d '{"name":"test"}'` |

Once these are in place, the validator should detect every CVE that has a
working MSF or NSE check.

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

### Fail — no MSF detection module exists in installed MSF version

I attempted to add three MSF modules (`apache_shiro_check`,
`oracle_weblogic_ssrf`, `mongo_express_rce`) to `MSF_MODULE_CATALOG`. After
rebuild + revalidation, all three still failed with **0 vulns reported**.

Manual `search` + `info` against the running metasploit pod (2026-04-11):

| Target | CVE | Module I tried | Actual MSF state |
|---|---|---|---|
| shiro-deser | CVE-2016-4437 | `auxiliary/scanner/http/apache_shiro_check` | **Module does not exist** in installed MSF. Only `exploit/multi/http/shiro_rememberme_v124_deserialize` exists, and it has `Check supported: No` (would have to actually exploit, not safe in validator). |
| weblogic-ssrf | CVE-2014-4210 | `auxiliary/scanner/http/oracle_weblogic_ssrf` | **Module does not exist.** None of the 18 weblogic modules cover SSRF. |
| mongo-express-rce | CVE-2019-10758 | `exploit/linux/http/mongo_express_rce` | **Module does not exist.** No mongo-express modules at all. |

The catalog additions were reverted in the same commit that added them
(replaced with a comment block explaining why). Rebuild not required —
the running scanning-console will keep emitting `[-] Failed to load module`
warnings until next image rebuild, but no functional impact.

### Fail — MSF module exists but `Check supported: No`

Discovered during the same investigation:

| Target | CVE | Module in catalog | Check supported? |
|---|---|---|---|
| weblogic-xmldecoder | CVE-2017-10271 | `exploit/multi/http/oracle_weblogic_wsat_deserialization_rce` | **No** |
| (shiro-deser if we used the exploit) | CVE-2016-4437 | `exploit/multi/http/shiro_rememberme_v124_deserialize` | **No** |

For these, `check_only: True` in the catalog is a no-op — MSF reports the
module ran but cannot determine vulnerability without exploitation.

### Fail — MSF module exists, check supported, but returned no vuln

| Target | CVE | Module | Check supported? | Status |
|---|---|---|---|---|
| tomcat-put | CVE-2017-12615 | `exploit/multi/http/tomcat_jsp_upload_bypass` | **Yes** | Check ran but did not report vulnerable. Needs manual kubectl-exec probe to determine why (Vulhub may ship Tomcat with PUT method blocked by default servlet config). |

### Path forward for these 5 targets

Detection must come from one of:

1. **OpenVAS NVTs** — Greenbone has CVE-specific NVTs for shiro, WebLogic SSRF,
   WebLogic XMLDecoder, and Tomcat PUT. This is the planned **Phase B**.
2. **Custom HTTP probe** — a tiny scanner that curls each target's known
   vulnerable endpoint and reports CVE matches based on response patterns:
   - shiro: `Set-Cookie: rememberMe=deleteMe` in any response
   - weblogic-ssrf: `GET /uddiexplorer/SearchPublicRegistries.jsp` returns 200
   - mongo-express: `Server: mongo-express` header + `/db/admin/` accessible
   - weblogic-xmldecoder: `GET /wls-wsat/CoordinatorPortType` returns 200
   - tomcat-put: `OPTIONS /` returns `Allow:` header containing PUT
3. **Nmap NSE scripts** — `http-vuln-cve2017-12615` exists; we could add it
   to nmap_scripts in the catalog.

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

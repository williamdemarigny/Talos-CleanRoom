# Scanning Console — Rebuild & Redeploy Guide

Quick-reference for deploying code changes to the Scanning Console after committing to git. All build commands run on the **Build VM (VMID 201)** accessed via the **Proxmox host (pve01)**.

---

## Architecture Recap

```
Developer workstation
  ├── git push → GitHub (refactor/restructure)
  │
  └── ssh → pve01.knowledgeondemand.net (Proxmox host)
              └── pct exec 201 → Build VM (10.83.3.191)
                    ├── git pull
                    ├── docker build → scanning-console:latest
                    ├── docker push → Harbor registry
                    └── kubectl rollout restart → K8s pod refresh
```

| Component | Location |
|-----------|----------|
| Source code | `refactor/restructure` branch on GitHub |
| Build VM | VMID 201 on pve01, IP 10.83.3.191 |
| Proxmox host | `root@pve01.knowledgeondemand.net` |
| Repo path (Build VM) | `/opt/talos-cleanroom` |
| Dockerfile | `scanning-app/Dockerfile` (build context = repo root) |
| Image | `harbor.knowledgeondemand.net/cleanroom/scanning-console:latest` |
| K8s namespace | `scanning-console` |
| URL | `https://scan.knowledgeondemand.net` |

---

## Step 1 — Commit & Push

From your development machine:

```bash
git add <files>
git commit -m "description of changes"
git push origin refactor/restructure
```

---

## Step 2 — SSH to Proxmox Host

```bash
ssh root@pve01.knowledgeondemand.net
```

All remaining steps are run from this shell.

---

## Step 3 — Pull Latest Code on Build VM

```bash
pct exec 201 -- bash -c '
  cd /opt/talos-cleanroom &&
  git fetch origin &&
  git reset --hard origin/refactor/restructure
'
```

---

## Step 4 — Build & Push Docker Image

```bash
pct exec 201 -- bash -c '
  cd /opt/talos-cleanroom &&
  docker build -f scanning-app/Dockerfile \
    -t harbor.knowledgeondemand.net/cleanroom/scanning-console:latest . &&
  docker push harbor.knowledgeondemand.net/cleanroom/scanning-console:latest
'
```

Build time is typically 1-2 minutes. The Dockerfile is a multi-stage build (builder + production image) with kubectl baked in. Vulhub manifests from `apps/vulhub-targets/manifests/` are copied into the image at `/app/vulhub-manifests/`.

---

## Step 5 — Restart the Scanning Console Pod

```bash
pct exec 201 -- kubectl rollout restart deployment/scanning-console -n scanning-console
```

Watch for the new pod to come up:

```bash
pct exec 201 -- kubectl get pods -n scanning-console -w
```

Wait until the new pod shows `Running` with `1/1` ready and the old pod terminates. The Alembic init container runs any pending DB migrations automatically before the app starts.

---

## Step 6 — Verify

Exit the Proxmox host and visit:

- **Target Lab:** `https://scan.knowledgeondemand.net/target-lab`
- **Scan page:** `https://scan.knowledgeondemand.net/scan`
- **Health check:** `https://scan.knowledgeondemand.net/api/system/health`

---

## One-Liner (Steps 3-5 Combined)

For quick redeployments after pushing to git:

```bash
ssh root@pve01.knowledgeondemand.net "
  pct exec 201 -- bash -c '
    cd /opt/talos-cleanroom &&
    git fetch origin &&
    git reset --hard origin/refactor/restructure &&
    docker build -f scanning-app/Dockerfile \
      -t harbor.knowledgeondemand.net/cleanroom/scanning-console:latest . &&
    docker push harbor.knowledgeondemand.net/cleanroom/scanning-console:latest &&
    kubectl rollout restart deployment/scanning-console -n scanning-console
  '
"
```

---

## Troubleshooting

### Build fails — image pull errors
Harbor registry must be accessible from the Build VM. Check:
```bash
pct exec 201 -- docker login harbor.knowledgeondemand.net
```

### Pod stuck in CrashLoopBackOff
Check init container (Alembic migration) and app container logs:
```bash
pct exec 201 -- kubectl logs deployment/scanning-console -n scanning-console -c db-migrate
pct exec 201 -- kubectl logs deployment/scanning-console -n scanning-console -c scanning-console
```

### Pod not pulling new image
Since the tag is `:latest`, K8s may cache the old image. The `rollout restart` forces a new pod which re-pulls. If it still uses the old image, verify the push succeeded:
```bash
pct exec 201 -- docker images | grep scanning-console
```

### Vulhub manifests missing inside container
The Dockerfile copies `apps/vulhub-targets/manifests/` into the image. If new manifests aren't found, the build context may be wrong. The Dockerfile must be built from the **repo root**:
```bash
docker build -f scanning-app/Dockerfile -t ... .    # note the trailing dot
```

---

## Also Applies To

The same pattern works for the **Portal** app — just substitute:

| | Scanning Console | Portal |
|-|-----------------|--------|
| Dockerfile | `scanning-app/Dockerfile` | `portal/Dockerfile` |
| Image | `cleanroom/scanning-console:latest` | `cleanroom/portal:latest` |
| Namespace | `scanning-console` | `portal` |
| Deployment | `scanning-console` | `portal` |
| URL | `scan.knowledgeondemand.net` | `cleanroom.knowledgeondemand.net` |

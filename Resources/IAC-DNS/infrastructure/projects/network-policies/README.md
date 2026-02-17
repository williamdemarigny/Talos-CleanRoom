# Network Policies

This directory contains Kubernetes NetworkPolicies for namespace isolation and security.

## Overview

NetworkPolicies implement zero-trust networking principles by:
1. Denying all traffic by default
2. Explicitly allowing only required connections
3. Limiting attack surface between namespaces

## Policy Overview

| Namespace     | Default Policy | Ingress Allowed From | Egress Allowed To |
|---------------|---------------|---------------------|-------------------|
| faraday       | deny-all      | traefik             | postgres (local), metasploit |
| openvas       | deny-all      | traefik             | internet (feed sync), DNS |
| threat-dragon | deny-all      | traefik             | DNS only |
| metasploit    | deny-all      | faraday             | any (pentesting requirement) |
| argocd        | deny-all      | traefik             | git repos, k8s API, DNS |

## Deployment

Apply all policies:
```bash
kubectl apply -f network-policies/
```

Apply specific policy:
```bash
kubectl apply -f network-policies/faraday-policy.yaml
```

## Testing Policies

### Test that faraday cannot reach external internet directly:
```bash
kubectl exec -n faraday deployment/faraday -c faraday -- curl -s --max-time 5 https://example.com
# Should timeout or fail
```

### Test that faraday can reach its local postgres:
```bash
kubectl exec -n faraday deployment/faraday -c faraday -- pg_isready -h 127.0.0.1
# Should succeed
```

### Test that threat-dragon is properly isolated:
```bash
kubectl exec -n threat-dragon deployment/threat-dragon -- wget -qO- --timeout=5 http://faraday.faraday.svc.cluster.local:5985
# Should fail (no egress to faraday)
```

## Important Notes

1. **DNS Access**: Most policies allow egress to kube-system for DNS resolution (UDP 53)
2. **Metasploit Exception**: Metasploit needs unrestricted egress for penetration testing
3. **OpenVAS Feed Sync**: OpenVAS requires internet egress to sync vulnerability feeds
4. **ArgoCD**: Needs access to git repositories and the Kubernetes API server

## Rollback

To remove all policies and restore default (allow all) behavior:
```bash
kubectl delete -f network-policies/
```

## Troubleshooting

If a service stops working after applying policies:

1. Check pod logs for connection errors
2. Verify the policy allows required traffic:
   ```bash
   kubectl describe networkpolicy <policy-name> -n <namespace>
   ```
3. Test connectivity with curl/wget from within the pod
4. Temporarily remove the policy to confirm it's the cause

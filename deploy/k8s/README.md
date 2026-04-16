# Kubernetes Notes

The current owned baseline starts with Docker Compose because it is the fastest path to a full local stack.

## Recommended next steps
- convert `knowledge-service`, `rag-service`, and `web-admin` into separate Deployments and Services
- move Prometheus and Grafana configuration into ConfigMaps
- replace local JSON persistence in `knowledge-service` with MinIO + vector index backed storage before production rollout
- externalize admin secrets into SealedSecrets or the cluster secret manager

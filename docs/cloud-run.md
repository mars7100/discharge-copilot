# Cloud Run deployment

Verified on 2026-10-10.

| Setting | Value |
| --- | --- |
| Project | `spotime-axjobo-2026` |
| Region | `us-central1` |
| Service | `dispatch-copilot` |
| URL | https://dispatch-copilot-z24qhdjsba-uc.a.run.app |
| Ready revision | `dispatch-copilot-00001-cnj`, 100% traffic |
| Image | `us-central1-docker.pkg.dev/spotime-axjobo-2026/cloud-run-source-deploy/dispatch-copilot@sha256:7a7d7e4bafb4d1276a4e3e48d996dfbf163750a083ec5fd52a9898b61aa66570` |
| Runtime model | `LLM_MODEL=gpt-6-luna` |
| Runtime key reference | `OPENAI_API_KEY=dispatch-copilot-openai-api-key:1` in Secret Manager |
| Service identity | `1070754648588-compute@developer.gserviceaccount.com` |
| Secret IAM grant | `roles/secretmanager.secretAccessor` on this secret only |
| Access | Public invocation, ingress `all` |
| Instance limits | Minimum 1, maximum 1 |
| Resources | 1 vCPU, 512 MiB, CPU always allocated |
| Request timeout | 600 seconds |
| Concurrency | Cloud Run default of 80 requests per instance |

Cloud Run resolved the pinned OCI index to its `linux/amd64` manifest,
`sha256:29f86c098a85d4b8b9907320c92f6a21845c7f3432fb7d8af31cdbf95f51f4c1`.
`docker buildx imagetools inspect` verified that this manifest belongs to the requested index.

Secret Manager API is enabled. The key was parsed from local `.env` with the existing
virtual environment's `python-dotenv` and sent through subprocess stdin to Secret Manager.
The image contains no runtime key from this deployment.

One warm instance with always-allocated CPU incurs idle compute charges. Background load
threads continue after an HTTP disconnect. Sessions and graph checkpoints live in process
memory and reset on restart or redeployment. Instance limits do not provide durable sessions.

## Verification

Unauthenticated requests to `/`, `/api/cases`, `/docs`, and `/openapi.json` returned HTTP 200.
Session creation rejected an invalid case with HTTP 404.

The live `case_001` load streamed six `note_extracted` events, followed by `extraction_done`
and `conflicts_found`. Its stored state contained 97 clinical events and one conflict.
The smoke session remains paused for review. Draft generation and review were not exercised.

## Deployment command reference

This command reuses the pinned secret version without reading or rotating its value.

```sh
gcloud run deploy dispatch-copilot \
    --project=spotime-axjobo-2026 \
    --region=us-central1 \
    --image=us-central1-docker.pkg.dev/spotime-axjobo-2026/cloud-run-source-deploy/dispatch-copilot@sha256:7a7d7e4bafb4d1276a4e3e48d996dfbf163750a083ec5fd52a9898b61aa66570 \
    --service-account=1070754648588-compute@developer.gserviceaccount.com \
    --set-secrets=OPENAI_API_KEY=dispatch-copilot-openai-api-key:1 \
    --set-env-vars=LLM_MODEL=gpt-6-luna \
    --allow-unauthenticated --ingress=all \
    --timeout=600 --max-instances=1 --min-instances=1 \
    --no-cpu-throttling --cpu=1 --memory=512Mi --port=8080
```

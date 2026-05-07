# Deployment

The repo ships two Bicep templates:

| File                  | Scope        | What it provisions                                                  |
| --------------------- | ------------ | ------------------------------------------------------------------- |
| `infra/minimal.bicep` | Resource group | AI Services + `gpt-4.1` GlobalStandard. For local dev / testing.   |
| `infra/main.bicep`    | Subscription | RG + AI Services + Search + Redis + Key Vault + App Insights + App Service Linux container. Full v1 production stack. |

## Quick — minimal (local dev)

```bash
az login
az group create -n rg-audvoice -l uaenorth
az deployment group create -g rg-audvoice -f infra/minimal.bicep
```

Then grant your user the Entra roles (one-time, per-subscription):

```bash
AI_ID=$(az cognitiveservices account list -g rg-audvoice --query "[0].id" -o tsv)
OBJ=$(az ad signed-in-user show --query id -o tsv)
for role in "Cognitive Services User" "Cognitive Services OpenAI User" "Cognitive Services Speech User"; do
  az role assignment create --assignee-object-id $OBJ --assignee-principal-type User \
    --role "$role" --scope "$AI_ID"
done
```

Now `uvicorn audvoice.main:app` runs locally against real Azure with `az login`.

## Production — full stack

### 1. Build and push the image

```bash
ACR=audvoice$(openssl rand -hex 3)
az acr create -g rg-audvoice -n $ACR --sku Basic
az acr login -n $ACR

cd apps/orchestrator
docker build -t $ACR.azurecr.io/audvoice:0.1.0 .
docker push  $ACR.azurecr.io/audvoice:0.1.0
```

### 2. Deploy

```bash
export AUDVOICE_JWT_SECRET=$(openssl rand -base64 48)
export AUDVOICE_API_KEYS="prodkey1:tenantA,prodkey2:tenantB"
az deployment sub create \
  --location uaenorth \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters containerImage=$ACR.azurecr.io/audvoice:0.1.0
```

The template:

- Uses **System-Assigned Managed Identity** on the App Service.
- Auto-grants the identity Speech + OpenAI roles on the AI Services resource (or grant manually if your subscription policy blocks role assignments from templates).
- Reads `AUDVOICE_JWT_SECRET` and `AUDVOICE_API_KEYS` from Key Vault references — no plaintext secrets in App Service.
- Enables WebSockets, ARR affinity, HTTP/2, Premium v3 P1v3 (required for sustained WS).

### 3. Verify

```bash
APP=$(az webapp list -g rg-audvoice --query "[0].defaultHostName" -o tsv)
curl https://$APP/healthz                      # → {"status":"ok"}
curl -X POST https://$APP/v1/sessions \
  -H "X-API-Key: prodkey1" -H "Content-Type: application/json" -d '{}'
```

Open `apps/web-demo/index.html` in any browser, point Server at `https://$APP`, and start talking.

## CI/CD

`.github/workflows/ci.yml` runs unit tests on every push. For container build + deploy, add a workflow that:

1. Logs in to Azure with OIDC (`azure/login@v2`).
2. Builds and pushes the image to ACR.
3. Runs `az webapp config container set` to roll the new image.

We don't ship that workflow because every team has a different Azure auth model — wire it to your federation.

## Region choice

| Need                                               | Pick                              |
| -------------------------------------------------- | --------------------------------- |
| Strict UAE residency for Speech                    | `uaenorth` (this is the whole point) |
| Lowest LLM latency                                 | Run AI Services in `swedencentral`, accept LLM-leaves-region |
| Sovereign / classified                             | Different stack — Core42, not this repo |

You **can** split: AI Services for Speech in UAE North, a second AI Services for OpenAI in Sweden Central. Set `AZURE_OPENAI_ENDPOINT` to the Sweden one and `AZURE_SPEECH_RESOURCE_ID` to the UAE one. Latency improves, residency for STT/TTS preserved, LLM data leaves UAE.

## Quotas & scale

- **Speech**: ~100 concurrent recognition + 200 concurrent synthesis per resource by default. [Quotas](https://learn.microsoft.com/azure/ai-services/speech-service/speech-services-quotas-and-limits).
- **Azure OpenAI**: tokens/min per deployment. Request increase before launch.
- **App Service P1v3**: ~250 concurrent WebSocket sessions per instance with our default config. Scale out horizontally; sessions are sticky via ARR affinity.

## Observability

App Insights is wired in via `APPLICATIONINSIGHTS_CONNECTION_STRING`. Custom events you'll see:

- `session.created`, `session.closed`, `session.duration_ms`
- `barge_in.detected` — count + spoken_chars histogram
- `llm.tokens` — prompt + completion per turn
- `error` — by `code`

Log Analytics queries live in `infra/queries/` (planned).

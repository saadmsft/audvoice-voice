# Getting started

Run the service locally and have a voice conversation against your own Azure resources in under 5 minutes.

## Prerequisites

- Python 3.10+
- An Azure subscription
- Azure CLI (`az login`)
- One Azure AI Services (or separate Speech + OpenAI) resource. Speech must live in **UAE North** for residency; Azure OpenAI deployment can be whatever's available to you (in UAE North that means `gpt-4.1` GlobalStandard).

## 1. Provision Azure (one-time)

```bash
az login
az group create -n rg-audvoice -l uaenorth
az deployment group create -g rg-audvoice \
  -f infra/minimal.bicep
```

This creates an AI Services resource and a `gpt-4.1` GlobalStandard deployment. Then grant your user the Entra roles:

```bash
AI=$(az cognitiveservices account list -g rg-audvoice --query "[0].id" -o tsv)
OBJ=$(az ad signed-in-user show --query id -o tsv)
for role in "Cognitive Services User" "Cognitive Services OpenAI User" "Cognitive Services Speech User"; do
  az role assignment create --assignee-object-id $OBJ --assignee-principal-type User \
    --role "$role" --scope "$AI"
done
```

## 2. Configure

```bash
cd apps/orchestrator
cp .env.example .env
```

Edit `.env`:

```bash
AZURE_SPEECH_REGION=uaenorth
AZURE_SPEECH_RESOURCE_ID=<full ARM id of the AI resource>
AZURE_OPENAI_ENDPOINT=https://<your-ai-resource>.cognitiveservices.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4.1

AUDVOICE_JWT_SECRET=<32+ bytes of randomness>
AUDVOICE_API_KEYS=devkey:tenant-dev   # comma-separated key:tenant pairs

DEFAULT_VOICE=en-US-AvaMultilingualNeural
DEFAULT_LANGUAGES=ar-AE,ar-SA,en-US,en-GB
```

> **No keys?** That's intentional. The orchestrator uses `DefaultAzureCredential`, so `az login` is enough locally and a Managed Identity is enough in App Service.

## 3. Run

```bash
pip install -e 'apps/orchestrator[dev]'
uvicorn audvoice.main:app --port 8088
```

In a second terminal:

```bash
cd apps/web-demo
python3 -m http.server 5173
open http://127.0.0.1:5173
```

In the page: confirm the server URL is `http://127.0.0.1:8088` and the API key is `devkey`. Click **Start**, allow microphone, and speak.

Speak in English (`"What is the capital of the UAE?"`), Arabic (`"ما هي عاصمة الإمارات؟"`), or code-switch — the service runs continuous Language ID across `ar-AE`, `ar-SA`, `en-US`, `en-GB`.

## 4. Programmatic test

```bash
pip install -e 'packages/client_py[mic]'
python tests/live_smoke.py
```

You should see:

```
[1/4] TTS synth (en-US)... <bytes>, ~2s
[2/4] STT recognize (UAE North)... 'What is the capital of the United Arab Emirates?', ~3s
[3/4] gpt-4.1 streaming reply... 'The capital of the UAE is Abu Dhabi.', ~4s
[4/4] TTS synth reply... <bytes>, ~2s
```

## Next

- Embed it in your app: see [SDKs](sdk.md).
- Plug a different model: see [LLM backends](llm-backends.md).
- Use it as a voice surface for an Agent Framework agent: see [Agent Framework integration](integration-agent-framework.md).
- Push it to Azure: see [Deployment](deployment.md).

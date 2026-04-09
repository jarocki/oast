# Audit Report: openai-python External Service Calls & Telemetry

**Repository:** https://github.com/openai/openai-python
**Date:** 2026-04-09
**Scope:** External service calls, telemetry mechanisms, and changes required for local-only model usage

---

## 1. External Service Calls Identified

### 1.1 OpenAI API (Primary - Hardcoded Default)

**File:** `src/openai/_client.py`
**Default Base URL:**
```python
base_url = f"https://api.openai.com/v1"
```

All API resource classes (`completions`, `chat`, `embeddings`, `images`, `audio`, `files`, `models`, `moderations`, `fine_tuning`, `batches`, `realtime`, `uploads`, `vector_stores`, `evals`, `containers`, `conversations`, `responses`, `videos`, `webhooks`, `skills`) route through this default endpoint.

**Environment variable override:** `OPENAI_BASE_URL` allows changing the default, and the `base_url` constructor parameter also supports override.

### 1.2 Azure OpenAI Endpoints

**File:** `src/openai/lib/azure.py`
**URL pattern:**
```python
base_url = f"{azure_endpoint.rstrip('/')}/openai/deployments/{azure_deployment}"
base_url = f"{azure_endpoint.rstrip('/')}/openai"
```

The Azure client (`AzureOpenAI` / `AsyncAzureOpenAI`) constructs URLs from user-provided `azure_endpoint` values. Reads from environment variable `AZURE_OPENAI_ENDPOINT`.

### 1.3 GritQL Binary Download (GitHub)

**File:** `src/openai/cli/_tools/migrate.py`
**URL:**
```
https://github.com/getgrit/gritql/releases/latest/download/{file_name}.tar.gz
```

The `openai migrate` CLI command downloads a third-party binary (GritQL) from GitHub to perform code migration from v0 to v1 of the SDK. This binary is:
- Downloaded via `httpx.Client()` to `~/.cache/openai-python/.install/bin/grit`
- Executed via `subprocess.check_call()`
- Platform-specific (macOS/Linux only, no Windows support)

**Risk:** Downloads and executes an unsigned binary from an external repository at runtime.

### 1.4 Workload Identity Authentication (Cloud Metadata Services)

**File:** `src/openai/auth/_workload.py`

This module contacts **three external services** for OAuth/identity federation when Workload Identity authentication is configured:

| Hardcoded URL | Service | When Contacted |
|---------------|---------|---------------|
| `https://auth.openai.com/oauth/token` | OpenAI OAuth token exchange | When using Workload Identity auth (default token exchange URL, overridable via constructor) |
| `http://169.254.169.254/metadata/identity/oauth2/token` | Azure Instance Metadata Service (IMDS) | When running on Azure with managed identity |
| `http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity` | GCP Metadata Server | When running on GCP with service account |

Additionally reads Kubernetes service account tokens from:
- `/var/run/secrets/kubernetes.io/serviceaccount/token` (standard k8s path, hardcoded)

**Risk:** These endpoints are only contacted when Workload Identity is explicitly configured, but the URLs are hardcoded and could leak identity tokens to cloud metadata services. For air-gapped or local-only deployments, this module should be disabled or removed.

### 1.5 WebSocket Connections (Realtime API)

**File:** `src/openai/resources/realtime/realtime.py`
**Endpoint:** Derived from the base URL with scheme conversion (`https` -> `wss`) + `/realtime` path.

```python
ws_scheme = "ws" if scheme == "http" else "wss"
base_url = self.___client._base_url.copy_with(scheme=ws_scheme)
```

Can be overridden via the `websocket_base_url` client parameter.

### 1.6 HuggingFace

**Result: NO references found.** A code search for `huggingface`, `hugging_face`, and `hf_hub` across the entire repository returned zero matches. The openai-python library has **no HuggingFace integration or dependency**.

### 1.7 Weights & Biases (wandb) - Server-Side Fine-Tuning Integration

**Result: 8 files with references** - This is an API-level integration for fine-tuning job monitoring.

Key files:
| File | Role |
|------|------|
| `src/openai/types/fine_tuning/fine_tuning_job_wandb_integration.py` | Defines `FineTuningJobWandbIntegration` model (`project`, `entity`, `name`, `tags`) |
| `src/openai/types/fine_tuning/fine_tuning_job_wandb_integration_object.py` | Wraps integration with `type: Literal["wandb"]` discriminator |
| `src/openai/types/fine_tuning/fine_tuning_job_integration.py` | Type alias: `FineTuningJobIntegration = FineTuningJobWandbIntegrationObject` |
| `src/openai/types/fine_tuning/fine_tuning_job.py` | `Optional[List[FineTuningJobWandbIntegrationObject]]` on `FineTuningJob` |
| `src/openai/types/fine_tuning/job_create_params.py` | `IntegrationWandb` TypedDict for creating jobs with W&B |

**Important distinction:** This is a **server-side** integration. The `wandb` Python package is NOT imported as a dependency. The client sends W&B configuration parameters to the OpenAI API, and OpenAI's servers handle the actual W&B reporting during fine-tuning. However, it does mean that fine-tuning jobs can be configured to send training metrics to Weights & Biases servers (`api.wandb.ai`), which is a third-party service.

**Risk for local-only usage:** Low if not using OpenAI fine-tuning. For complete isolation, remove the wandb integration types from `src/openai/types/fine_tuning/`.

### 1.8 Other Third-Party Analytics Services

**Result: NO references found.** Code searches confirmed zero matches for:
- Sentry
- Datadog
- OpenTelemetry
- Segment
- Mixpanel
- Amplitude

---

## 2. Telemetry & Metadata Collection Mechanisms

### 2.1 Stainless SDK Headers (Sent with Every Request)

**File:** `src/openai/_base_client.py`

Every HTTP request includes these headers that fingerprint the client environment:

| Header | Data Collected |
|--------|---------------|
| `User-Agent` | `OpenAI/Python {version}` |
| `X-Stainless-Lang` | `"python"` |
| `X-Stainless-Package-Version` | SDK version string |
| `X-Stainless-OS` | Operating system (MacOS, Linux, Windows, iOS, Android, FreeBSD, OpenBSD) |
| `X-Stainless-Arch` | CPU architecture (x32, x64, arm, arm64) |
| `X-Stainless-Runtime` | Python implementation (CPython, PyPy, etc.) |
| `X-Stainless-Runtime-Version` | Python version string |
| `X-Stainless-Async` | `"false"` or `"async:{library}"` (e.g., `async:asyncio`) |
| `x-stainless-retry-count` | Number of retries attempted |
| `x-stainless-read-timeout` | Timeout value for the request |

**Platform detection functions:**
```python
def get_platform() -> Platform:      # platform.system(), platform.platform()
def get_architecture() -> Arch:       # platform.machine()
def get_python_runtime() -> str:      # platform.python_implementation()
def get_python_version() -> str:      # platform.python_version()
```

These are cached via `@lru_cache` and sent on every API call. While they don't constitute a separate telemetry endpoint, they provide detailed client environment profiling to whichever server receives the requests.

### 2.2 Organization & Project Headers

**File:** `src/openai/_client.py`
```python
"OpenAI-Organization": self.organization   # from OPENAI_ORG_ID env var
"OpenAI-Project": self.project             # from OPENAI_PROJECT_ID env var
```

### 2.3 No Background Telemetry

- No background threads or async tasks that report usage
- No "phone home" endpoints
- No separate analytics or telemetry HTTP calls
- Logging is local-only via Python's standard `logging` module
- `SensitiveHeadersFilter` redacts auth headers from logs

---

## 3. Dependencies Assessment

### Required Dependencies
| Package | Risk Level | Notes |
|---------|-----------|-------|
| `httpx` | Low | HTTP client - no telemetry |
| `pydantic` | Low | Data validation - no telemetry |
| `typing-extensions` | None | Type hints only |
| `anyio` | Low | Async I/O - no telemetry |
| `distro` | Low | OS detection (used for `X-Stainless-OS` header) |
| `sniffio` | None | Async library detection |
| `tqdm` | None | Progress bars - local only |
| `jiter` | None | JSON parsing - local only |

### Optional Dependencies
| Package | Risk Level | Notes |
|---------|-----------|-------|
| `numpy` | None | Numerical computation |
| `pandas` | None | Data processing |
| `websockets` | Low | Used for Realtime API connections |
| `aiohttp` / `httpx_aiohttp` | Low | Alternative HTTP transport |
| `sounddevice` | None | Audio I/O for voice helpers |

**No telemetry, analytics, or tracking packages in any dependency tier.**

---

## 4. Environment Variables Read

| Variable | Purpose | Read At |
|----------|---------|---------|
| `OPENAI_API_KEY` | API authentication | Client init |
| `OPENAI_ORG_ID` | Organization header | Client init |
| `OPENAI_PROJECT_ID` | Project header | Client init |
| `OPENAI_BASE_URL` | Override default API base URL | Client init |
| `OPENAI_WEBHOOK_SECRET` | Webhook verification | Client init |
| `OPENAI_LOG` | Logging level (debug/info) | Module import |
| `OPENAI_API_TYPE` | "openai" or "azure" | Module import |
| `OPENAI_API_VERSION` | API version string | Module import |
| `AZURE_OPENAI_ENDPOINT` | Azure endpoint URL | Module import / Azure client init |
| `AZURE_OPENAI_AD_TOKEN` | Azure AD authentication | Module import / Azure client init |
| `AZURE_OPENAI_API_KEY` | Azure API key | Azure client init |
| `XDG_CACHE_HOME` | Cache dir for grit binary | CLI migrate command |

---

## 5. Changes Required for Local-Only Model Usage

### 5.1 Override Base URL (Minimum Required Change)

The simplest approach - set `base_url` to point to a local inference server (e.g., vLLM, llama.cpp, Ollama, LocalAI):

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"  # most local servers accept any value
)
```

Or via environment variable:
```bash
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="not-needed"
```

**Assessment:** This redirects all API calls but does NOT prevent the metadata headers from being sent.

### 5.2 Strip Stainless Telemetry Headers

To prevent environment fingerprinting, override the default headers:

```python
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed",
    default_headers={
        "X-Stainless-Lang": "",
        "X-Stainless-Package-Version": "",
        "X-Stainless-OS": "",
        "X-Stainless-Arch": "",
        "X-Stainless-Runtime": "",
        "X-Stainless-Runtime-Version": "",
        "X-Stainless-Async": "",
        "OpenAI-Organization": "",
        "OpenAI-Project": "",
    }
)
```

**For a permanent fix**, modify `src/openai/_base_client.py`:
- Remove or conditionally disable the `platform_headers()` function
- Remove `X-Stainless-*` headers from `default_headers` property
- Remove `x-stainless-retry-count` and `x-stainless-read-timeout` from `_build_headers()`

### 5.3 Remove or Disable the Migration Tool's Binary Download

**File:** `src/openai/cli/_tools/migrate.py`

Either:
- Remove the `migrate` CLI command entirely
- Replace the GritQL download with a local-only alternative
- Add a flag to skip the download and require a pre-installed grit binary

### 5.4 Remove or Disable Workload Identity Authentication

**File:** `src/openai/auth/_workload.py`

This module contacts external cloud metadata services and OpenAI's OAuth server. For local-only usage:
- Remove or stub out the `_workload.py` module
- Ensure `workload_identity` parameter is never passed to the client constructor
- This prevents any calls to `auth.openai.com`, Azure IMDS (`169.254.169.254`), or GCP metadata (`metadata.google.internal`)
- Also prevents reading Kubernetes service account tokens from `/var/run/secrets/kubernetes.io/serviceaccount/token`

### 5.5 Remove Azure Integration (If Not Needed)

**File:** `src/openai/lib/azure.py`

If running purely local models, remove or disable:
- `AzureOpenAI` / `AsyncAzureOpenAI` classes
- Azure environment variable reads (`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_AD_TOKEN`, `AZURE_OPENAI_API_KEY`)

### 5.6 Guard the Default Base URL

To prevent accidental calls to `api.openai.com`, modify `src/openai/_client.py`:

```python
# Instead of:
base_url = f"https://api.openai.com/v1"

# Use:
base_url = os.environ.get("OPENAI_BASE_URL")
if base_url is None:
    raise ValueError(
        "OPENAI_BASE_URL must be set. Direct calls to api.openai.com are disabled."
    )
```

### 5.7 Disable WebSocket Realtime Connections to OpenAI

If using the Realtime API locally, ensure `websocket_base_url` is explicitly set to a local endpoint. Otherwise, the client derives the WebSocket URL from the base URL (which would hit `wss://api.openai.com` by default).

---

## 6. Summary of Findings

| Category | Finding |
|----------|---------|
| **HuggingFace calls** | None found |
| **Weights & Biases (wandb)** | Server-side integration in fine-tuning API types (8 files); no client-side `wandb` import |
| **Third-party analytics** | None found (no Sentry, Datadog, OpenTelemetry, Segment, Mixpanel, Amplitude) |
| **Background telemetry** | None - no phone-home, no background threads |
| **External binary download** | Yes - GritQL from GitHub (CLI migrate tool only) |
| **Environment fingerprinting** | Yes - 8 `X-Stainless-*` headers sent with every API request |
| **Hardcoded OpenAI URL** | Yes - `https://api.openai.com/v1` as default base URL |
| **Workload Identity auth** | Contacts `auth.openai.com`, Azure IMDS, GCP metadata (only when explicitly configured) |
| **Azure endpoints** | Configurable, not hardcoded (user provides endpoint) |
| **Override mechanism** | Available via `base_url` parameter or `OPENAI_BASE_URL` env var |

### Risk Summary for Local-Only Usage

1. **HIGH:** Default base URL sends all requests to `api.openai.com` if not overridden
2. **MEDIUM:** Every request includes OS, architecture, Python version, and SDK version headers that fingerprint the client environment
3. **MEDIUM:** Workload Identity module has hardcoded URLs to `auth.openai.com`, Azure IMDS (`169.254.169.254`), and GCP metadata server - contacted only when Workload Identity is explicitly configured
4. **LOW:** CLI migration tool downloads/executes a third-party binary from GitHub
5. **LOW:** Weights & Biases integration types in fine-tuning API (server-side only, no client-side wandb import)
6. **NONE:** No HuggingFace calls, no third-party analytics SDKs (Sentry, Datadog, OpenTelemetry, etc.)

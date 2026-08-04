# Compliance — what this product calls at runtime

Written so a reviewer, or a screening tool, can settle the question without
reading the whole tree.

## AI services the application calls

| Service | Where | SDK |
|---|---|---|
| Gemini — video understanding, classification, claim extraction, evidence comparison, caption drafting | `app/clients/gemini_client.py` | `google-genai` |
| Google Agent Development Kit — one `LlmAgent` orchestrating six tools | `app/adk_pipeline.py` | `google-adk` |
| Parallel Search API — live verification of claims that clear the confidentiality gate | `app/clients/parallel_client.py` | `parallel-web` |

**No other AI service, model API or agent framework is invoked by the
application.** There is no OpenAI, Anthropic, AWS Bedrock, Azure OpenAI, Cohere,
Mistral, LangChain, LlamaIndex, AutoGen, CrewAI or Semantic Kernel dependency,
import or HTTP call anywhere in `services/agent/app/`.

Everything else in the stack is deterministic and non-AI: FFmpeg for the cut,
FastAPI and Pydantic for the service, openpyxl for the caption sheet, Pillow and
PyMuPDF for reading a programme's own paper order form, Cloud Run and Secret
Manager for hosting and keys.

## How to check it yourself

```bash
# No forbidden AI dependency reaches the product.
grep -rEn "openai|anthropic|claude|langchain|llama_index|llamaindex|bedrock|cohere|mistralai|autogen|crewai|semantic_kernel" services/agent/app/ services/agent/requirements.txt

# The official SDKs are imported and actually called.
grep -rn "from google import genai\|google.adk\|from parallel import Parallel" services/agent/app/
```

The first command returns nothing. The second shows the three call sites in the
table above.

## Runtime evidence

Every run records which provider served each step. `GET /projects/{id}/trace`
returns one row per agent with the provider named — `gemini`, `parallel`,
`adk`, `ffmpeg` — so the claim above is checkable against a live run rather than
taken on trust.

The Parallel Search API is not decorative. It is the only route by which any
claim gets verified, and every outbound call is written to the Egress Log before
it is sent and again after it returns: `GET /projects/{id}/egress`.

## Development tooling

Editors, assistants and review scripts used while building this are not invoked
by the product and are not part of the submitted repository. The rule governs
what the Project uses; the table above is that list, in full.

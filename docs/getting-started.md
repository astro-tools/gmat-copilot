# Getting started

## Install

```bash
pip install gmat-copilot
```

The base install is light and GMAT-free. Add the provider you intend to use as an extra:

```bash
pip install "gmat-copilot[anthropic]"   # Claude, via your ANTHROPIC_API_KEY
pip install "gmat-copilot[openai]"      # OpenAI, via your OPENAI_API_KEY
pip install "gmat-copilot[ollama]"      # a local Ollama server
```

## Choose a model

There is no default model. Selection is always explicit, as `provider:model`:

| Provider | Example selector | Credential |
| --- | --- | --- |
| Anthropic | `anthropic:claude-...` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai:gpt-...` | `OPENAI_API_KEY` |
| Ollama | `ollama:llama3` | local server (`OLLAMA_HOST`) |
| GitHub Models | `github:openai/gpt-4.1-mini` | `GH_TOKEN` / `MODELS_PAT` |

With no selection the tool errors and lists the providers it can reach from your configured
credentials.

## Draft from the library

```python
from gmat_copilot import draft

result = draft(
    "A 500 km circular Earth orbit at 51.6 degrees inclination; "
    "propagate one day and report altitude and semi-major axis.",
    model="anthropic:claude-...",
)

print(result.script)        # the generated GMAT .script text
print(result.lint.clean)    # did it lint clean?
print(result.provider, result.model, result.usage)

result.save("mission.script")   # write the script to a file
```

The returned [`CopilotResult`](api.md) carries the script, its lint report, the retrieval trace, and
the provider/model/usage.

## Draft from the CLI

```bash
gmat-copilot draft "a sun-synchronous orbit at 700 km" --model anthropic:claude-...
gmat-copilot validate mission.script        # lint an existing script
gmat-copilot validate mission.script --permissive
```

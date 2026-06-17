# Add a provider

gmat-copilot ships adapters for [Anthropic, OpenAI, Ollama, and GitHub Models](../providers.md), but
the provider abstraction is open: any backend that can turn a prompt into text can generate drafts.
A provider is just an object matching one protocol — there is nothing to subclass.

## Implement the protocol

A provider needs a `name`, a `reachable()` check, and a `complete()` that returns a `Completion`:

```python
from gmat_copilot.providers import Completion


class MyProvider:
    """Generate through some other backend."""

    name = "myco"

    def reachable(self) -> bool:
        # True when a call could succeed now — e.g. a credential or host is configured.
        return True

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> Completion:
        text = my_backend_call(prompt, model=model, temperature=temperature, max_tokens=max_tokens)
        return Completion(text=text, provider=self.name, model=model, usage={})
```

`Provider` is a runtime-checkable protocol, so matching the shape is enough —
`isinstance(MyProvider(), Provider)` is `True` without inheritance. Populate `usage` with whatever
integer token counts your backend reports (it may be left empty).

## Use it

Pass the provider straight to `draft`. When you supply `provider`, the `model` argument is the bare
model name handed to it (no `provider:` prefix):

```python
from gmat_copilot import draft

result = draft(
    "a 500 km circular Earth orbit at 51.6 degrees; propagate one day and report altitude",
    provider=MyProvider(),
    model="my-model-name",
)

print(result.provider, result.model)   # "myco" "my-model-name"
print(result.lint.clean)
```

Everything downstream is unchanged: the draft is still retrieval-grounded, validated by the
[lint gate](../validation.md), and returned as a [`CopilotResult`](../output-schema.md).

## Notes

- The four built-in selectors (`anthropic:`, `openai:`, `ollama:`, `github:`) are what the CLI
  resolves; a custom provider is a library-level extension you wire in through the `provider=`
  argument.
- Raise `ProviderError` for a missing credential or an unreachable backend so failures surface
  clearly, consistent with the built-in adapters.
- To record a custom provider's output for deterministic replay, wrap it in a `RecordingProvider`;
  see the [provider surface](../api.md) and the [evaluation suite](../evaluation.md).

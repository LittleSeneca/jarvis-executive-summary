"""DataSourcePlugin ABC and associated data types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "DataSourcePlugin",
    "FetchResult",
]


@dataclass(slots=True)
class FetchResult:
    source_name: str
    raw_payload: Any
    metadata: dict = field(default_factory=dict)
    links: list[str] = field(default_factory=list)


class DataSourcePlugin(ABC):
    """Define the contract every data-source plugin must satisfy."""

    # --- Identity ---
    name: str
    display_name: str

    # --- Environment ---
    required_env_vars: list[str]

    # --- Inference parameters ---
    temperature: float = 0.2
    max_tokens: int = 800
    model_override: str | None = None

    @abstractmethod
    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull the last `window_hours` of activity from the source."""
        ...

    def prompt_template(self) -> str:
        """Return the Jinja2 prompt template for this plugin.

        Loads prompt.md from the same directory as the plugin module by default.
        """
        prompt_path = Path(self.__class__.__module__.replace(".", "/")).parent / "prompt.md"
        if not prompt_path.exists():
            # Walk up via importlib to locate the file reliably
            import importlib
            mod = importlib.import_module(self.__class__.__module__)
            prompt_path = Path(mod.__file__).parent / "prompt.md"
        return prompt_path.read_text()

    def chunker(self):
        """Return a callable that splits an oversized payload into chunks.

        The default splits on top-level JSON array elements. Override in
        chunker.py when the plugin's payload shape demands it.
        """
        from jarvis.core.summarizer import default_chunker
        return default_chunker

    def redact(self, payload: Any) -> Any:
        """Scrub sensitive fields from payload before it is sent to Groq."""
        return payload

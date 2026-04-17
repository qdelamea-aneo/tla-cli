"""LLM-powered error explanation for TLC output.

This module provides :func:`explain_tlc_error`, which sends a TLC log (and
optionally a formatted error trace) to a configurable LLM backend and streams
a human-readable explanation back to the terminal using Rich Markdown rendering.

Supported backends
------------------

``claude`` (default)
    Anthropic Claude.  Requires ``pip install anthropic`` and
    ``ANTHROPIC_API_KEY``.

``openai``
    OpenAI ChatGPT.  Requires ``pip install openai`` and ``OPENAI_API_KEY``.

``gemini``
    Google Gemini.  Requires ``pip install google-generativeai`` and
    ``GEMINI_API_KEY``.

``mistral``
    Mistral AI.  Requires ``pip install mistralai`` and ``MISTRAL_API_KEY``.
"""

import os

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Iterator, Optional

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.rule import Rule

if TYPE_CHECKING:
    from .tlc import TLCRun


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_EXPLAIN_PROMPT = """\
You are an expert TLA+ developer and formal methods engineer.

The TLC model checker produced the output below. Analyse it and write a clear,
actionable explanation aimed at the developer who wrote the spec.

Focus on:
1. What the root cause of the error is (be precise — name the module, line, and
   symbol when available).
2. Why TLC reports it the way it does.
3. Concrete steps the developer should take to fix it.
{trace_guidance}
Be concise. Use Markdown with short paragraphs and bullet lists. Do **not**
repeat the raw TLC output verbatim; paraphrase and highlight what matters.

<tlc_output>
{log_content}
</tlc_output>
"""

_TRACE_GUIDANCE = """\
4. Explain what the error trace reveals about the system's behaviour — which
   sequence of state transitions led to the violation and why that sequence
   is problematic.

"""

# Maximum characters of TLC log sent to the model — avoids blowing the context
# window on very large logs while still capturing all the relevant error info.
_MAX_LOG_CHARS = 12_000


# ---------------------------------------------------------------------------
# Abstract backend
# ---------------------------------------------------------------------------


class LLMBackend(ABC):
    """Abstract base class for LLM streaming backends.

    Concrete subclasses must implement :meth:`stream_explanation` and expose a
    :attr:`display_name` property.  All SDK imports and environment-variable
    checks are performed in ``__init__`` so that errors surface early.
    """

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name of the backend shown in the terminal header."""
        ...

    @abstractmethod
    def stream_explanation(self, prompt: str) -> Iterator[str]:
        """Stream text chunks from the LLM for the given prompt.

        Args:
            prompt: The full prompt to send to the model.

        Yields:
            Successive text chunks as they arrive from the model.
        """
        ...


# ---------------------------------------------------------------------------
# Concrete backends
# ---------------------------------------------------------------------------


class ClaudeBackend(LLMBackend):
    """Anthropic Claude backend.

    Requires the ``anthropic`` package and ``ANTHROPIC_API_KEY``.

    Args:
        model: Claude model ID to use (default: ``"claude-sonnet-4-6"``).
    """

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        try:
            import anthropic  # type: ignore[import]
            self._anthropic = anthropic
        except ImportError:
            raise ImportError(
                "anthropic package not installed — run: pip install anthropic"
            )
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set.")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    @property
    def display_name(self) -> str:
        """Return the display name for this backend."""
        return "Claude"

    def stream_explanation(self, prompt: str) -> Iterator[str]:
        """Stream text from Anthropic Claude.

        Args:
            prompt: The prompt to send.

        Yields:
            Text chunks from the streaming response.
        """
        with self._client.messages.stream(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for chunk in stream.text_stream:
                yield chunk


class OpenAIBackend(LLMBackend):
    """OpenAI ChatGPT backend.

    Requires the ``openai`` package and ``OPENAI_API_KEY``.

    Args:
        model: OpenAI model ID to use (default: ``"gpt-4o"``).
    """

    def __init__(self, model: str = "gpt-4o") -> None:
        try:
            import openai  # type: ignore[import]
            self._openai = openai
        except ImportError:
            raise ImportError(
                "openai package not installed — run: pip install openai"
            )
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set.")
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    @property
    def display_name(self) -> str:
        """Return the display name for this backend."""
        return "ChatGPT (OpenAI)"

    def stream_explanation(self, prompt: str) -> Iterator[str]:
        """Stream text from OpenAI.

        Args:
            prompt: The prompt to send.

        Yields:
            Text chunks from the streaming response.
        """
        stream = self._client.chat.completions.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content


class GeminiBackend(LLMBackend):
    """Google Gemini backend.

    Requires the ``google-generativeai`` package and ``GEMINI_API_KEY``.

    Args:
        model: Gemini model name to use (default: ``"gemini-1.5-pro"``).
    """

    def __init__(self, model: str = "gemini-1.5-pro") -> None:
        try:
            import google.generativeai as genai  # type: ignore[import]
            self._genai = genai
        except ImportError:
            raise ImportError(
                "google-generativeai package not installed — run: "
                "pip install google-generativeai"
            )
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
        genai.configure(api_key=api_key)
        self._model_instance = genai.GenerativeModel(model)

    @property
    def display_name(self) -> str:
        """Return the display name for this backend."""
        return "Gemini"

    def stream_explanation(self, prompt: str) -> Iterator[str]:
        """Stream text from Google Gemini.

        Args:
            prompt: The prompt to send.

        Yields:
            Text chunks from the streaming response.
        """
        for chunk in self._model_instance.generate_content(prompt, stream=True):
            if chunk.text:
                yield chunk.text


class MistralBackend(LLMBackend):
    """Mistral AI backend.

    Requires the ``mistralai`` package and ``MISTRAL_API_KEY``.

    Args:
        model: Mistral model name to use (default: ``"mistral-large-latest"``).
    """

    def __init__(self, model: str = "mistral-large-latest") -> None:
        try:
            from mistralai import Mistral  # type: ignore[import]
            self._Mistral = Mistral
        except ImportError:
            raise ImportError(
                "mistralai package not installed — run: pip install mistralai"
            )
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("MISTRAL_API_KEY environment variable is not set.")
        self._client = self._Mistral(api_key=api_key)
        self._model = model

    @property
    def display_name(self) -> str:
        """Return the display name for this backend."""
        return "Mistral"

    def stream_explanation(self, prompt: str) -> Iterator[str]:
        """Stream text from Mistral AI.

        Args:
            prompt: The prompt to send.

        Yields:
            Text chunks from the streaming response.
        """
        stream = self._client.chat.stream(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        for event in stream:
            delta = event.data.choices[0].delta
            if delta.content:
                yield delta.content


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

BACKENDS: dict[str, type[LLMBackend]] = {
    "claude": ClaudeBackend,
    "openai": OpenAIBackend,
    "gemini": GeminiBackend,
    "mistral": MistralBackend,
}

BACKEND_NAMES = list(BACKENDS.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def explain_tlc_error(
    log_content: str,
    console: Console,
    *,
    backend_name: str = "claude",
    tlc_run: Optional["TLCRun"] = None,
) -> None:
    """Send a TLC log to an LLM and stream a formatted explanation to the terminal.

    The function is a no-op (printing a clear warning) when the requested
    backend's SDK is not installed or its API key is absent, rather than
    raising an exception.

    When *tlc_run* is provided and contains an error trace, the prompt
    instructs the model to also explain the trace's significance.

    The LLM response is streamed and rendered progressively as Rich Markdown
    in a :class:`~rich.live.Live` block.

    Args:
        log_content: Full text of the TLC run log (``tlc.log``).
        console: Rich :class:`~rich.console.Console` used for all output.
        backend_name: One of ``"claude"``, ``"openai"``, ``"gemini"``,
            ``"mistral"`` (default: ``"claude"``).
        tlc_run: Optional populated :class:`~cli.tools.tlc.TLCRun`.  When
            present and a trace exists, the prompt asks for trace analysis.
    """
    BackendClass = BACKENDS.get(backend_name)
    if BackendClass is None:
        console.print(
            f"[yellow]⚠ Unknown LLM backend: '{backend_name}'. "
            f"Choose one of: {', '.join(BACKEND_NAMES)}.[/yellow]"
        )
        return

    try:
        backend = BackendClass()
    except (ImportError, ValueError) as exc:
        console.print(f"[yellow]⚠ {exc}[/yellow]")
        return

    truncated = log_content[:_MAX_LOG_CHARS]
    if len(log_content) > _MAX_LOG_CHARS:
        truncated += "\n[... log truncated ...]"

    has_trace = tlc_run is not None and bool(getattr(tlc_run, "trace", None))
    prompt = _EXPLAIN_PROMPT.format(
        log_content=truncated,
        trace_guidance=_TRACE_GUIDANCE if has_trace else "",
    )

    console.print()
    console.print(
        Rule(
            f"[bold cyan]LLM Explanation ({backend.display_name})[/bold cyan]",
            style="cyan",
        )
    )
    console.print()

    accumulated = ""
    try:
        with Live("", console=console, refresh_per_second=15) as live:
            for chunk in backend.stream_explanation(prompt):
                accumulated += chunk
                live.update(Markdown(accumulated))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]LLM request failed:[/red] {exc}")
        return

    console.print()

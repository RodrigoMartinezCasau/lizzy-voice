"""Cerebro de Lizzy — interfaz con Anthropic."""

from __future__ import annotations

from dataclasses import dataclass

import anthropic

from jarvis.brain.capabilities import build_capabilities
from jarvis.brain.prompt import build_system_prompt
from jarvis.logger import JarvisLogger


@dataclass
class Brain:
    api_key: str
    model: str
    user_name: str
    max_tokens: int
    logger: JarvisLogger
    assistant_name: str = "Lizzy"
    _client: anthropic.Anthropic | None = None

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("ANTHROPIC_API_KEY no configurada")
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def think(
        self,
        user_text: str,
        context: str,
        *,
        capabilities: str = "",
        dev_workspace: str = "",
        live_context: str = "",
    ) -> str:
        caps = capabilities or build_capabilities(
            self.user_name, dev_workspace, assistant_name=self.assistant_name
        )
        live = live_context or ""
        system = build_system_prompt(
            self.user_name,
            context,
            assistant_name=self.assistant_name,
            capabilities=caps,
            live_context=live,
        )
        self.logger.info(f"Consulta: {user_text[:120]}")

        try:
            client = self._get_client()
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"{user_text}\n\n"
                            "[Responde únicamente en español de España. "
                            "Máximo 2 frases salvo que sea imprescindible.]"
                        ),
                    }
                ],
            )
        except Exception as exc:
            self.logger.error(f"Error API Anthropic: {exc}")
            return "No puedo conectar con el cerebro ahora mismo. Revisa el modelo en la configuración."

        text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        ).strip()

        if not text:
            text = "No he podido formular una respuesta."

        self.logger.info(f"Respuesta: {text[:120]}")
        return text

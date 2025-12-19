"""
OpenRouter LLM integration for LangChain.
Provides OpenRouterLLM class that wraps ChatOpenAI for OpenRouter API.
"""
import os
import logging
from typing import Optional, List, Dict, Any, Union
from langchain_openai import ChatOpenAI
from langchain_core.language_models.llms import LLM
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.messages import BaseMessage
from pydantic.v1 import PrivateAttr
from core.config import LLMConfig
from core.services.langsmith_client import get_callback_manager, configure_langsmith_environment

logger = logging.getLogger(__name__)

# Configure LangSmith at module import time
configure_langsmith_environment()


class OpenRouterLLM(LLM):
    """
    OpenRouter LLM wrapper that provides a simple interface similar to the example.
    Uses ChatOpenAI under the hood with OpenRouter's API endpoint.
    """

    api_key: str = ""
    model: str = "openai/gpt-3.5-turbo"
    temperature: float = 0.2
    streaming: bool = False
    base_url: str = "https://openrouter.ai/api/v1"

    _chat_model: ChatOpenAI = PrivateAttr()

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        streaming: bool = False,
        callbacks: Optional[Any] = None,
        **kwargs
    ):
        resolved_api_key = api_key or LLMConfig.get_api_key()
        resolved_model = model or LLMConfig.get_model()
        resolved_temperature = temperature if temperature is not None else LLMConfig.get_temperature()
        resolved_base_url = kwargs.pop(
            "base_url",
            os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        )

        # IMPORTANT: pass fields into the Pydantic/LangChain constructor
        super().__init__(
            api_key=resolved_api_key,
            model=resolved_model,
            temperature=resolved_temperature,
            streaming=streaming,
            base_url=resolved_base_url,
            **kwargs,
        )

        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is required")

        # Get LangSmith callbacks if not provided and LangSmith is configured
        if callbacks is None:
            callbacks = get_callback_manager(
                tags=["openrouter", "llm"],
                metadata={
                    "model": resolved_model,
                    "temperature": resolved_temperature,
                    "provider": "openrouter",
                }
            )

        # Create internal ChatOpenAI instance with callbacks
        self._chat_model = ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            api_key=self.api_key,
            base_url=self.base_url,
            callbacks=callbacks,
        )

    @property
    def _llm_type(self) -> str:
        """Return type of LLM."""
        return "openrouter"

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        """Call the LLM with a prompt string."""
        # Convert prompt to messages format
        messages = [{"role": "user", "content": prompt}]
        response = self._chat_model.invoke(messages)
        return response.content

    async def _acall(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        """Async call the LLM with a prompt string."""
        messages = [{"role": "user", "content": prompt}]
        response = await self._chat_model.ainvoke(messages)
        return response.content

    def invoke(
        self,
        messages: Union[List[Dict[str, str]], List[BaseMessage]],
        **kwargs: Any
    ) -> BaseMessage:
        """
        Invoke the chat model with messages synchronously.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
                     or list of BaseMessage objects
            **kwargs: Additional arguments to pass to the chat model

        Returns:
            Chat message response from the model
        """
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Invoking LLM with {len(messages)} messages, model: {self.model}")
        return self._chat_model.invoke(messages, **kwargs)

    async def ainvoke(
        self,
        messages: Union[List[Dict[str, str]], List[BaseMessage]],
        **kwargs: Any
    ) -> BaseMessage:
        """
        Async invoke the chat model with messages.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
                     or list of BaseMessage objects
            **kwargs: Additional arguments to pass to the chat model

        Returns:
            Chat message response from the model
        """
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Async invoking LLM with {len(messages)} messages, model: {self.model}")
        return await self._chat_model.ainvoke(messages, **kwargs)

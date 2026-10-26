"""
Base interface for messaging adapters in Tracky AI.
"""

from abc import ABC, abstractmethod


class BaseMessenger(ABC):
    @abstractmethod
    async def start(self) -> None:
        """Starts the adapter (e.g. begins polling or registers handlers)."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Shuts down the adapter gracefully."""
        pass

    @abstractmethod
    async def send_message(self, recipient_id: str, text: str) -> bool:
        """Sends an outbound proactive text message to a user or chat."""
        pass

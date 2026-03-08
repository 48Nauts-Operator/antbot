"""Message bus module for decoupled channel-agent communication."""

from antbot.bus.events import InboundMessage, OutboundMessage
from antbot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]

"""Chat channels module with plugin architecture."""

from antbot.channels.base import BaseChannel
from antbot.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]

"""
INDI Tools - Comprehensive INDI development and testing toolkit

This package provides tools for developing and testing INDI clients, including:
- Event recording and replay system
- Mock INDI servers for testing
- Comprehensive pytest integration
- Example clients and utilities

Modules:
    event_recorder: Record INDI events from live servers
    event_replayer: Replay recorded events for testing
    testing: Pytest fixtures and testing utilities
    usage_example: Example usage and demonstrations
"""

__version__ = "1.0.0"
__author__ = "PiFinder Team"

# Import main components for easy access
from .event_recorder import IndiEventRecorder
from .event_replayer import IndiEventReplayer

__all__ = ["IndiEventRecorder", "IndiEventReplayer"]

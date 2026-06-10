"""Artifact management — track and store agent conversation outputs."""

from local_agent.artifacts.manager import ArtifactManager
from local_agent.artifacts.models import Artifact

__all__ = ["Artifact", "ArtifactManager"]

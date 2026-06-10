from local_agent.agent.models import AgentInstance, Persona

__all__ = ["AgentInstance", "AgentManager", "AgentRuntime", "Persona"]


def __getattr__(name: str):
    if name == "AgentManager":
        from local_agent.agent.manager import AgentManager

        return AgentManager
    if name == "AgentRuntime":
        from local_agent.agent.runtime import AgentRuntime

        return AgentRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

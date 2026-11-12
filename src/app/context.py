from dataclasses import dataclass

@dataclass
class Ctx:
    """Per-request runtime context shared by tools and the dynamic prompt."""
    session_id: str
    user_id: str = ""
    token: str = ""

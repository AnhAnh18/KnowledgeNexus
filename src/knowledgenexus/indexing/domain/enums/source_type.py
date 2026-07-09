from enum import StrEnum


class SourceType(StrEnum):
    CONFLUENCE = "CONFLUENCE"
    FILE = "FILE"
    URL = "URL"
    MCP = "MCP"
    
    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value.upper() in cls.values()

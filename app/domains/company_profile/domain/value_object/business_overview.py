from dataclasses import dataclass, field


@dataclass(frozen=True)
class BusinessOverview:
    summary: str
    revenue_sources: list[str] = field(default_factory=list)
    source: str = "llm_only"  # "rag_summary" | "llm_only"

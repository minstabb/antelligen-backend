"""LangGraph 멀티 에이전트 워크플로우 스모크 테스트.

실행:
    python -m app.infrastructure.langgraph.smoke_test
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def main() -> None:
    from app.infrastructure.langgraph.runner import run_workflow

    print("=" * 60)
    print("LangGraph 멀티 에이전트 스모크 테스트")
    print("=" * 60)

    result = await run_workflow("안녕")

    print(f"\n[status]     {result['status']}")
    print(f"[iteration]  {result['iteration']}")
    print(f"[nodes]      {[m['role'] for m in result['messages']]}")
    print(f"\n[final_output]\n{result['final_output']}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations
from fastapi import APIRouter, Depends
from synapse.api.schemas import CMDBQueryRequest, CMDBQueryResponse
from synapse.tools.cmdb_query import get_ci_dependencies_text, search_affected_cis

router = APIRouter(prefix="/cmdb", tags=["cmdb"])


@router.post("/query", response_model=CMDBQueryResponse)
async def cmdb_query(body: CMDBQueryRequest) -> CMDBQueryResponse:
    """Natural-language CMDB question — read-only."""
    question = body.question.strip()

    # Simple dispatch: if question mentions a known CI pattern, return dependency info
    cis = await search_affected_cis(question)
    if cis:
        ci_id = cis[0]["id"]
        answer = await get_ci_dependencies_text(ci_id)
        return CMDBQueryResponse(answer=answer, rows=cis[:5])

    return CMDBQueryResponse(
        answer=f"No CI found matching: {question}",
        rows=[],
    )

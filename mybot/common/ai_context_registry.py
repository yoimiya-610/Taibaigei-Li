from mybot.common.ai_capability_prompt import PUBLIC_CAPABILITY_DATABASE
from mybot.common.ai_context import AIContextRequest, AIContextRouter
from mybot.common.ai_public_play_guides import PUBLIC_PLAY_GUIDE_DATABASE


AI_CONTEXT_DATABASES = (
    PUBLIC_CAPABILITY_DATABASE,
    PUBLIC_PLAY_GUIDE_DATABASE,
)

AI_CONTEXT_ROUTER = AIContextRouter(AI_CONTEXT_DATABASES)


def build_relevant_ai_context(
    message: str,
    *,
    group_id: str | int | None = None,
    user_id: str | int | None = None,
) -> str:
    request = AIContextRequest(
        message=message,
        group_id=group_id,
        user_id=user_id,
    )
    return AI_CONTEXT_ROUTER.build_context(request)

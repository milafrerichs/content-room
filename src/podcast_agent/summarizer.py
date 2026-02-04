from pydantic_ai import Agent

from .models import PodcastSummary

_INSTRUCTIONS = (
    "You are a podcast summarizer. Given a transcript, produce a structured summary.\n\n"
    "Guidelines:\n"
    "- one_sentence_summary: A single sentence capturing the core message of the episode.\n"
    "- main_points: 5-10 key points discussed in the episode, each as a concise sentence.\n"
    "- takeaways: 3-5 actionable takeaways or lessons for the listener.\n"
    "- topics: 3-5 topic tags that categorize the episode content.\n\n"
    "Be concise and factual. Do not add opinions or information not present in the transcript."
)

_agent: Agent[None, PodcastSummary] | None = None


def _get_agent() -> Agent[None, PodcastSummary]:
    global _agent
    if _agent is None:
        _agent = Agent(
            "anthropic:claude-haiku-4-5",
            output_type=PodcastSummary,
            instructions=_INSTRUCTIONS,
        )
    return _agent


async def summarize_transcript(transcript: str) -> PodcastSummary:
    agent = _get_agent()
    result = await agent.run(transcript)
    return result.output

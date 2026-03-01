from typing import Literal

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.providers.ollama import OllamaProvider

from .models import Insights, MicroSummary, PodcastSummary, Recommendations, SponsorInfo

# =============================================================================
# FABRIC PATTERN: extract_wisdom
# =============================================================================
_EXTRACT_WISDOM_INSTRUCTIONS = """# IDENTITY and PURPOSE

You extract surprising, insightful, and interesting information from podcast transcripts. You are interested in insights related to the purpose and meaning of life, human flourishing, the role of technology in the future of humanity, artificial intelligence and its affect on humans, memes, learning, reading, books, continuous improvement, and similar topics.

Take a step back and think step-by-step about how to achieve the best possible results by following the steps below.

# STEPS

- Extract a summary of the content in 25 words, including who is presenting and the content being discussed.

- Extract 20 to 50 of the most surprising, insightful, and/or interesting ideas from the input. If there are less than 50 then collect all of them. Make sure you extract at least 20.

- Extract 10 to 20 of the best insights from the input and from a combination of the raw input and the ideas above. These insights should be fewer, more refined, more insightful, and more abstracted versions of the best ideas in the content.

- Extract 15 to 30 of the most surprising, insightful, and/or interesting quotes from the input. Use the exact quote text from the input. Include the name of the speaker of the quote at the end.

- Extract 15 to 30 of the most practical and useful personal habits of the speakers, or mentioned by the speakers, in the content. Examples include but aren't limited to: sleep schedule, reading habits, things they always do, things they always avoid, productivity tips, diet, exercise, etc.

- Extract 15 to 30 of the most surprising, insightful, and/or interesting valid facts about the greater world that were mentioned in the content.

- Extract all mentions of writing, art, tools, projects and other sources of inspiration mentioned by the speakers. This should include any and all references to something that the speaker mentioned.

- Extract the most potent takeaway and recommendation into a 15-word sentence that captures the most important essence of the content.

- Extract 15 to 30 of the most surprising, insightful, and/or interesting recommendations that can be collected from the content.

# OUTPUT INSTRUCTIONS

- Write the ideas as exactly 16 words each.

- Write the recommendations as exactly 16 words each.

- Write the habits as exactly 16 words each.

- Write the facts as exactly 16 words each.

- Write the insights as exactly 16 words each.

- Extract at least 25 ideas from the content.

- Extract at least 10 insights from the content.

- Extract at least 20 items for quotes, habits, facts, and recommendations where possible.

- Do not repeat ideas, insights, quotes, habits, facts, or references.

- Do not start items with the same opening words.

- Ignore any advertisements or sponsor segments in the transcript.

- Focus on the actual content and wisdom being shared, not promotional material."""

# =============================================================================
# FABRIC PATTERN: extract_sponsors
# =============================================================================
_EXTRACT_SPONSORS_INSTRUCTIONS = """# IDENTITY and PURPOSE

You are an expert at extracting the sponsors and potential sponsors from a given transcript, such as from a podcast, video transcript, essay, or whatever.

# STEPS

- Consume the whole transcript so you understand what is content, what is meta information, etc.

- Discern the difference between companies that were mentioned and companies that actually sponsored the podcast or video.

- Extract official sponsors with their name, description, and URL if mentioned.

# OUTPUT INSTRUCTIONS

- Only include companies that officially sponsored the content in question.
- Format each sponsor as: "Name | Description | URL" (use "N/A" if URL not mentioned)
- Do not include companies that were merely mentioned in the content.
- If no sponsors are identified, return an empty list."""

# =============================================================================
# FABRIC PATTERN: summarize_micro
# =============================================================================
_SUMMARIZE_MICRO_INSTRUCTIONS = """# IDENTITY and PURPOSE

You are an expert content summarizer. You take content in and output a concise summary.

Take a deep breath and think step by step about how to best accomplish this goal.

# STEPS

- Combine all of your understanding of the content into a single, 20-word sentence for the one_sentence_summary.

- Extract the 3 most important points of the content as a list with no more than 12 words per point for main_points.

- Extract a list of the 3 best takeaways from the content in 12 words or less each for takeaways.

# OUTPUT INSTRUCTIONS

- Keep each bullet to 12 words or less.
- Do not repeat items in the output sections.
- Do not start items with the same opening words.
- Ignore any advertisements or sponsor segments."""

# =============================================================================
# FABRIC PATTERN: extract_insights
# =============================================================================
_EXTRACT_INSIGHTS_INSTRUCTIONS = """# IDENTITY and PURPOSE

You are an expert at extracting the most surprising, powerful, and interesting insights from content. You are interested in insights related to the purpose and meaning of life, human flourishing, the role of technology in the future of humanity, artificial intelligence and its affect on humans, memes, learning, reading, books, continuous improvement, and similar topics.

You create 8 word bullet points that capture the most surprising and novel insights from the input.

Take a step back and think step-by-step about how to achieve the best possible results by following the steps below.

# STEPS

- Extract 10 of the most surprising and novel insights from the input.
- Output them as 8 word bullets in order of surprise, novelty, and importance.
- Write them in the simple, approachable style of Paul Graham.

# OUTPUT INSTRUCTIONS

- Each insight must be exactly 8 words.
- Do not start items with the same opening words.
- Ignore any advertisements or sponsor segments."""

# =============================================================================
# FABRIC PATTERN: extract_recommendations
# =============================================================================
_EXTRACT_RECOMMENDATIONS_INSTRUCTIONS = """# IDENTITY and PURPOSE

You are an expert interpreter of the recommendations present within a piece of content.

# STEPS

Take the input given and extract the concise, practical recommendations that are either explicitly made in the content, or that naturally flow from it.

# OUTPUT INSTRUCTIONS

- Extract up to 20 recommendations, each of no more than 16 words.
- Focus on actionable, practical advice.
- Do not start items with the same opening words.
- Ignore any advertisements or sponsor segments."""

# =============================================================================
# Agent cache and model helpers
# =============================================================================
_agents: dict[str, Agent] = {}


def _get_model_spec(
    provider: Literal["anthropic", "ollama"],
    model: str,
    ollama_base_url: str = "http://localhost:11434/v1",
) -> str | OpenAIModel:
    """Get the model string or model instance for pydantic-ai."""
    if provider == "anthropic":
        return f"anthropic:{model}"
    elif provider == "ollama":
        ollama_provider = OllamaProvider(base_url=ollama_base_url)
        # Use 'prompted' mode: puts JSON schema in system prompt instead of tool
        # calling, which is far more compatible with small/local Ollama models.
        profile = ModelProfile(default_structured_output_mode="prompted")
        return OpenAIModel(model, provider=ollama_provider, profile=profile)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def _get_agent(
    pattern: str,
    output_type: type,
    instructions: str,
    provider: Literal["anthropic", "ollama"] = "ollama",
    model: str = "llama3.2",
    ollama_base_url: str = "http://localhost:11434/v1",
) -> Agent:
    """Get or create a cached agent for the given pattern and provider/model."""
    cache_key = f"{pattern}:{provider}:{model}:{ollama_base_url}"
    if cache_key not in _agents:
        model_spec = _get_model_spec(provider, model, ollama_base_url)
        _agents[cache_key] = Agent(
            model_spec,
            output_type=output_type,
            instructions=instructions,
        )
    return _agents[cache_key]


# =============================================================================
# Public API
# =============================================================================

async def extract_sponsors(
    transcript: str,
    provider: Literal["anthropic", "ollama"] = "ollama",
    model: str = "llama3.2",
    ollama_base_url: str = "http://localhost:11434/v1",
) -> SponsorInfo:
    """Extract sponsor information from a transcript.

    This should be run FIRST before other summarization to identify ad segments.

    Args:
        transcript: The podcast transcript text
        provider: LLM provider ("anthropic" or "ollama")
        model: Model name
        ollama_base_url: Base URL for Ollama server

    Returns:
        SponsorInfo with list of identified sponsors
    """
    agent = _get_agent(
        "extract_sponsors",
        SponsorInfo,
        _EXTRACT_SPONSORS_INSTRUCTIONS,
        provider,
        model,
        ollama_base_url,
    )
    result = await agent.run(transcript)
    return result.output


async def summarize_micro(
    transcript: str,
    provider: Literal["anthropic", "ollama"] = "ollama",
    model: str = "llama3.2",
    ollama_base_url: str = "http://localhost:11434/v1",
) -> MicroSummary:
    """Create a quick micro summary of a transcript.

    Args:
        transcript: The podcast transcript text
        provider: LLM provider ("anthropic" or "ollama")
        model: Model name
        ollama_base_url: Base URL for Ollama server

    Returns:
        MicroSummary with 20-word summary, 3 main points, 3 takeaways
    """
    agent = _get_agent(
        "summarize_micro",
        MicroSummary,
        _SUMMARIZE_MICRO_INSTRUCTIONS,
        provider,
        model,
        ollama_base_url,
    )
    result = await agent.run(transcript)
    return result.output


async def extract_insights(
    transcript: str,
    provider: Literal["anthropic", "ollama"] = "ollama",
    model: str = "llama3.2",
    ollama_base_url: str = "http://localhost:11434/v1",
) -> Insights:
    """Extract 10 key insights from a transcript (8 words each, Paul Graham style).

    Args:
        transcript: The podcast transcript text
        provider: LLM provider ("anthropic" or "ollama")
        model: Model name
        ollama_base_url: Base URL for Ollama server

    Returns:
        Insights with list of 10 eight-word insights
    """
    agent = _get_agent(
        "extract_insights",
        Insights,
        _EXTRACT_INSIGHTS_INSTRUCTIONS,
        provider,
        model,
        ollama_base_url,
    )
    result = await agent.run(transcript)
    return result.output


async def extract_recommendations(
    transcript: str,
    provider: Literal["anthropic", "ollama"] = "ollama",
    model: str = "llama3.2",
    ollama_base_url: str = "http://localhost:11434/v1",
) -> Recommendations:
    """Extract actionable recommendations from a transcript.

    Args:
        transcript: The podcast transcript text
        provider: LLM provider ("anthropic" or "ollama")
        model: Model name
        ollama_base_url: Base URL for Ollama server

    Returns:
        Recommendations with up to 20 actionable items (16 words each)
    """
    agent = _get_agent(
        "extract_recommendations",
        Recommendations,
        _EXTRACT_RECOMMENDATIONS_INSTRUCTIONS,
        provider,
        model,
        ollama_base_url,
    )
    result = await agent.run(transcript)
    return result.output


async def summarize_transcript(
    transcript: str,
    provider: Literal["anthropic", "ollama"] = "ollama",
    model: str = "llama3.2",
    ollama_base_url: str = "http://localhost:11434/v1",
) -> PodcastSummary:
    """Full extract_wisdom summarization of a transcript.

    Args:
        transcript: The podcast transcript text
        provider: LLM provider ("anthropic" or "ollama")
        model: Model name
        ollama_base_url: Base URL for Ollama server

    Returns:
        Full PodcastSummary with ideas, insights, quotes, habits, facts, references, recommendations
    """
    agent = _get_agent(
        "extract_wisdom",
        PodcastSummary,
        _EXTRACT_WISDOM_INSTRUCTIONS,
        provider,
        model,
        ollama_base_url,
    )
    result = await agent.run(transcript)
    return result.output


async def summarize_with_instructions(
    transcript: str,
    instructions: str,
    provider: Literal["anthropic", "ollama"] = "ollama",
    model: str = "llama3.2",
    ollama_base_url: str = "http://localhost:11434/v1",
) -> str:
    """Summarize a transcript with custom instructions.

    Args:
        transcript: The podcast transcript text
        instructions: Custom summarization instructions
        provider: LLM provider ("anthropic" or "ollama")
        model: Model name
        ollama_base_url: Base URL for Ollama server

    Returns:
        Custom summary as string
    """
    model_spec = _get_model_spec(provider, model, ollama_base_url)
    custom_agent: Agent[None, str] = Agent(
        model_spec,
        output_type=str,
        instructions=(
            f"You are a podcast summarizer. Summarize the following transcript "
            f"according to these instructions: {instructions}\n\n"
            "Be concise and factual. Do not add information not present in the transcript."
        ),
    )
    result = await custom_agent.run(transcript)
    return result.output

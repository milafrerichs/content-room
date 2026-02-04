#!/usr/bin/env python3
import asyncio
import yaml
from pathlib import Path
from datetime import datetime
from src.podcast_agent import PodcastAgent, AgentConfig, PodcastFeed


def load_config(config_path: str = "config.yaml") -> AgentConfig:
    """Load configuration from YAML file"""
    with open(config_path, 'r') as f:
        config_data = yaml.safe_load(f)

    # Convert feed data to PodcastFeed objects
    feeds = [PodcastFeed(**feed) for feed in config_data['rss_feeds']]

    # Create AgentConfig
    return AgentConfig(
        rss_feeds=feeds,
        download_dir=Path(config_data['download_dir']),
        transcript_dir=Path(config_data['transcript_dir']),
        summary_dir=Path(config_data['summary_dir']),
        max_episodes_per_day=config_data['max_episodes_per_day'],
        fabric_pattern=config_data['fabric_pattern'],
        mcp_endpoint=config_data.get('mcp_endpoint')
    )


async def main():
    """Main entry point"""
    print("🎧 Starting Podcast Agent...")

    # Load configuration
    config = load_config()

    # Create agent
    agent = PodcastAgent(config=config)

    # Run once immediately for testing
    results = await agent.run_daily_processing()

    print(f"\n📊 Processing Results:")
    for result in results:
        status = "✅" if result.success else "❌"
        print(f"{status} {result.episode.title} ({result.processing_time:.1f}s)")
        if not result.success:
            print(f"   Error: {result.error_message}")

    print(f"\n🕐 To run daily at 7:00 AM, use: python main.py --schedule")


async def summarize_mode():
    """Run summarization only on existing transcripts"""
    print("📝 Starting summarization of existing transcripts...")

    # Load configuration
    config = load_config()

    # Create agent
    agent = PodcastAgent(config=config)

    # Run summarization only
    results = await agent.run_summarization_only()

    print(f"\n📊 Summarization Results:")
    for result in results:
        status = "✅" if result.success else "❌"
        print(f"{status} {result.episode.title} ({result.processing_time:.1f}s)")
        if not result.success:
            print(f"   Error: {result.error_message}")


def test_notifications():
    """Test AppleScript notifications"""
    print("🧪 Testing AppleScript notifications...")

    # Load configuration
    config = load_config()

    # Create agent
    agent = PodcastAgent(config=config)

    # Test notification
    agent.send_notification(
        "Podcast Agent Test",
        "AppleScript integration is working!",
        "This is a test notification"
    )

    # Test alert (optional)
    response = input("\nShow test alert dialog? (y/N): ")
    if response.lower() == 'y':
        agent.show_alert("This is a test alert from Podcast Agent")

    # Test speech (optional)
    response = input("Test text-to-speech? (y/N): ")
    if response.lower() == 'y':
        agent.speak_text("Podcast Agent AppleScript integration is working correctly")

    # Test Notes saving (optional)
    response = input("Test Apple Notes integration? (y/N): ")
    if response.lower() == 'y':
        test_content = """# Test Podcast Summary

This is a test note created by the Podcast Agent.

## Key Points:
- AppleScript integration is working
- Notes are being saved correctly
- Content formatting is preserved

Generated at: """ + str(datetime.now())

        agent.save_to_notes("Test Podcast Summary", test_content, "Podcast Agent Test")
        print("📝 Test note saved to Apple Notes!")

    print("✅ AppleScript test complete!")


def schedule_mode():
    """Run in scheduled mode"""
    config = load_config()
    agent = PodcastAgent(config=config)

    print("🎧 Podcast Agent scheduled for daily runs at 7:00 AM")
    print("Press Ctrl+C to stop")

    try:
        agent.schedule_daily_run("07:00")
    except KeyboardInterrupt:
        print("\n👋 Stopping Podcast Agent")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "--schedule":
            schedule_mode()
        elif sys.argv[1] == "--summarize":
            asyncio.run(summarize_mode())
        elif sys.argv[1] == "--test-notifications":
            test_notifications()
        else:
            print("Usage: python main.py [--schedule|--summarize|--test-notifications]")
            print("  --schedule           Run daily at 7:00 AM")
            print("  --summarize          Summarize existing transcripts only")
            print("  --test-notifications Test AppleScript notifications")
    else:
        asyncio.run(main())
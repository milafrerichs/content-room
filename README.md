# Podcast Agent

An AI agent that automatically processes podcast RSS feeds daily, downloads new episodes, transcribes them using Whisper, and summarizes them using Fabric.

## Features

- <� Fetches podcast episodes from RSS feeds
-  Downloads new episodes automatically
- <� Transcribes audio using OpenAI Whisper
- =� Summarizes content using Fabric
- � Runs daily on schedule
- =' Configurable via YAML

## Setup

1. **Install dependencies**:
   ```bash
   uv sync
   ```

2. **Install Fabric** (if not already installed):
   ```bash
   # Follow fabric installation instructions
   go install github.com/danielmiessler/fabric@latest
   ```

3. **Configure RSS feeds** in `config.yaml`:
   ```yaml
   rss_feeds:
     - name: "Your Podcast"
       url: "https://example.com/rss"
   ```

## Usage

### Run Once (Test Mode)
```bash
python main.py
```

### Run on Schedule (Daily at 7:00 AM)
```bash
python main.py --schedule
```

### Summarize Existing Transcripts Only
```bash
python main.py --summarize
```
This will find all `.txt` files in the transcript directory and generate summaries for them (skipping any that already have summaries).

### Test AppleScript Notifications
```bash
python main.py --test-notifications
```
Test macOS notifications, alerts, and text-to-speech integration.

### Custom Configuration
Edit `config.yaml` to customize:
- RSS feed URLs
- Download/transcript/summary directories
- Maximum episodes per day
- Fabric summarization pattern
- MCP endpoint (optional)

## Configuration

The `config.yaml` file controls all agent behavior:

```yaml
rss_feeds:
  - name: "Podcast Name"
    url: "https://feeds.example.com/rss"

download_dir: "./downloads"      # Where audio files are saved
transcript_dir: "./transcripts"  # Where transcripts are saved
summary_dir: "./summaries"       # Where summaries are saved
max_episodes_per_day: 5         # Limit episodes processed
fabric_pattern: "summarize"     # Fabric pattern to use
mcp_endpoint: null              # Optional MCP integration

# AppleScript/macOS integration
notifications_enabled: true     # Send macOS notifications
speak_results: false           # Use text-to-speech for results
show_completion_alert: false   # Show completion dialog
save_to_notes: false           # Save summaries to Apple Notes
notes_folder: "Podcast Summaries"  # Notes folder name
```

## Output Structure

```
downloads/          # Original audio files
transcripts/        # Whisper transcriptions (.txt)
summaries/         # Fabric summaries (.md)
podcast_agent.log  # Processing logs
```

## Dependencies

- **pydantic**: Data validation and models
- **feedparser**: RSS feed parsing
- **requests/aiohttp**: HTTP client for downloads
- **openai-whisper**: Audio transcription
- **schedule**: Daily scheduling
- **pyyaml**: Configuration file parsing

## AppleScript Integration

The agent uses native macOS `osascript` command for system integration including:
- **Notifications**: Desktop notifications for processing status
- **Alerts**: Modal dialog boxes for completion status
- **Text-to-Speech**: Audio announcements of results
- **Apple Notes**: Automatic saving of podcast summaries to Notes app

## MCP Integration

The agent is designed to work with MCP (Model Context Protocol) for accessing RSS feeds. Set the `mcp_endpoint` in your config to use MCP instead of direct RSS fetching.

## Requirements

- Python 3.8+
- Fabric CLI tool installed and configured
- Sufficient disk space for audio files and transcripts



Improvenements:

Use this to allow me to click on the notification and open the summarizations:
https://macosxautomation.com/mavericks/notifications/01A.html

# sync2canvas

A Python tool that fetches Confluence pages and converts them to Slack Canvas documents. The tool automatically converts Confluence's HTML markup to Slack-compatible Markdown, preserves the original author information, and creates a new canvas in your specified Slack channel.

## Overview

`sync2canvas` fetches content from a Confluence page using your authentication cookies, converts the HTML to Markdown format compatible with Slack, and then creates a new Slack Canvas document in a specified channel. The tool generates both a local Markdown file and a JSON payload file for reference.

## Requirements

The following environment variables must be set:

- `AWSELB_COOKIE` - AWS ELB authentication cookie for Confluence. Log in to Sync, and copy the AWSELBAuthSessionCookie-0 cookie from your browser.
- `JSESSIONID` - JSESSIONID cookie for Confluence. Log in to Sync, and copy the JSESSIONID cookie from your browser.
- `SLACK_BOT_TOKEN` - Slack bot token with canvas creation permissions. Ask @ice for this.

## Arguments

- `-p, --page-id` **(required)** - The ID of the Confluence page to fetch
- `-c, --channel-id` **(required)** - The Slack channel ID where the canvas will be created
- `-u, --base-confluence-url` - The base URL for the Confluence instance (default: `https://sync.hudlnet.com`)

## Usage Examples

Basic usage:

```bash
python src/sync2canvas.py -p 123456789 -c C01234ABCDE
```

Using long-form arguments:

```bash
python src/sync2canvas.py --page-id 123456789 --channel-id C01234ABCDE
```

With a custom Confluence URL:

```bash
python src/sync2canvas.py -p 123456789 -c C01234ABCDE -u https://mycompany.atlassian.net
```

With environment variables set inline:

```bash
AWSELB_COOKIE="your-cookie" JSESSIONID="your-jsessionid" SLACK_BOT_TOKEN="xoxb-your-token" \
python src/sync2canvas.py -p 123456789 -c C01234ABCDE
```

## Output

The tool generates two files in the `output/` directory:

- `{page-title}.md` - Markdown file with the page title and formatted content
- `{page-title}_payload.json` - JSON payload containing title, markdown, and author information

A new Slack Canvas is also created in the specified channel with the converted content.

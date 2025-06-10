import re
import os
import json
import argparse
import html
import globals

from fileUtils import sanitize_filename
from networkUtils import create_slack_canvas, fetch_confluence_data

from bs4 import BeautifulSoup, NavigableString, CData

from handlers import (
    handle_a,
    handle_br,
    handle_children,
    handle_confluence_macro,
    handle_em,
    handle_h,
    handle_image,
    handle_li,
    handle_p,
    handle_strong,
)

TAG_MAPPINGS = {
    "p": handle_p,
    "h1": handle_h(1),
    "h2": handle_h(2),
    "h3": handle_h(3),
    "h4": handle_h(3),
    "h5": handle_h(3),
    "h6": handle_h(3),
    "li": handle_li,
    "ul": handle_children,
    "ol": handle_children,
    "br": handle_br,
    "a": handle_a,
    "em": handle_em,
    "i": handle_em,
    "strong": handle_strong,
    "b": handle_strong,
    "ac:image": handle_image,
    "ac:structured-macro": handle_confluence_macro,
}


def process_node(node):
    """
    Recursively processes a BeautifulSoup node and its children,
    converting them to Markdown based on defined mappings.
    """
    if isinstance(node, NavigableString):
        if isinstance(node, CData):
            return node
        text = str(node).replace("\xa0", " ")
        return re.sub(r"\s+", " ", text)
    if node.name in TAG_MAPPINGS:
        result = TAG_MAPPINGS[node.name](node, process_node)
        return result
    result = "".join(process_node(child) for child in node.children)
    return result


callout_counter = 0

# --- Mappings ---


def preprocess_code_blocks(html_content):
    """
    Finds CDATA in code blocks and HTML-encodes its content to protect it from the parser.
    """

    def replacer(match):
        # Extract the content inside the CDATA block
        cdata_content = match.group(1)
        # HTML-encode the content
        encoded_content = html.escape(cdata_content)
        # Return the plain-text-body tag with the encoded content
        return f"<ac:plain-text-body>{encoded_content}</ac:plain-text-body>"

    # This regex finds a plain-text-body tag containing a CDATA section and captures the CDATA content.
    # It handles multiline content with re.DOTALL.
    pattern = re.compile(
        r"<ac:plain-text-body>.*?<!\[CDATA\[(.*?)\]\]>.*?</ac:plain-text-body>",
        re.DOTALL,
    )

    return pattern.sub(replacer, html_content)


def convert_confluence_html_to_markdown(html_content):
    """
    Main function to convert a Confluence HTML string to Slack Markdown.

    Args:
        html_content (str): The raw HTML from Confluence.

    Returns:
        str: The converted Markdown string.
    """
    # Pre-process the HTML to handle CDATA blocks safely.
    safe_html = preprocess_code_blocks(html_content)

    # Use 'lxml' parser on the now-safe HTML.
    soup = BeautifulSoup(safe_html, "lxml")

    # Process the entire body of the parsed document, or the soup itself if no body tag.
    markdown_output = process_node(soup.body or soup)
    return re.sub(r"\n{3,}", "\n\n", markdown_output).strip()


# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(
        description="Fetches a Confluence page and converts it to Slack-compatible Markdown and a JSON API payload."
    )
    parser.add_argument(
        "-p", "--page-id", required=True, help="The ID of the Confluence page to fetch."
    )
    parser.add_argument(
        "-c", "--channel-id", required=True, help="The Slack channel ID for the canvas."
    )
    parser.add_argument(
        "-t",
        "--slack-bot-token",
        required=True,
        help="The Slack bot token for authentication.",
    )
    args = parser.parse_args()

    # Save the page id and slack bot token globally
    globals.PAGE_ID = args.page_id
    globals.SLACK_BOT_TOKEN = args.slack_bot_token

    # Check for environment variables
    aws_cookie = os.getenv("AWSELB_COOKIE")
    seraph_cookie = os.getenv("SERAPH_COOKIE")
    if not all([aws_cookie, seraph_cookie]):
        print("❌ Error: Missing required environment variables.")
        print(
            "Please set AWSELB_COOKIE and SERAPH_COOKIE with your Confluence authentication cookie values."
        )
        return

    cookies = {
        "AWSELBAuthSessionCookie-0": aws_cookie,
        "seraph.confluence": seraph_cookie,
    }

    # Fetch data from Confluence
    html_content, title, username = fetch_confluence_data(cookies)
    if html_content is None:
        return  # Exit if fetching failed

    # Perform the conversion
    print("🤖 Converting HTML to Markdown...")
    body_markdown = convert_confluence_html_to_markdown(html_content)
    print("✅ Conversion complete.")

    # Create two versions of the markdown content
    markdown_for_payload = f"_Original Author: {username}_\n\n{body_markdown}"
    markdown_for_file = f"# {title}\n\n{markdown_for_payload}"

    # Create Output Directory and Filenames
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    base_filename = sanitize_filename(title)
    md_output_path = os.path.join(output_dir, f"{base_filename}.md")
    # json_output_path = os.path.join(output_dir, f"{base_filename}_payload.json")

    # Write the Markdown File (with the title)
    with open(md_output_path, "w", encoding="utf-8") as f:
        f.write(markdown_for_file)
    print(f"✔️ Markdown file saved to: '{md_output_path}'")

    create_slack_canvas(
        channel_id=args.channel_id,
        title=title,
        markdown_content=markdown_for_payload,
    )


if __name__ == "__main__":
    main()

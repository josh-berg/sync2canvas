import re
import os
import json
import argparse
import html
from slack_sdk import WebClient

try:
    import requests
except ImportError:
    print("Error: The 'requests' library is not installed.")
    print("Please install it by running: pip install requests")
    exit(1)

from bs4 import BeautifulSoup, NavigableString, CData

# --- Helper Functions ---


def sanitize_filename(filename):
    """Removes invalid characters from a string to make it a valid filename."""
    return re.sub(r'[<>:"/\\|?*]', "-", filename).strip()


def fetch_confluence_data(page_id, cookies):
    """
    Fetches page content and metadata from Confluence APIs.

    Args:
        page_id (str): The ID of the Confluence page.
        cookies (dict): A dictionary of authentication cookies.

    Returns:
        A tuple containing (html_content, title, username) or (None, None, None) on failure.
    """
    base_url = "https://sync.hudlnet.com"
    storage_url = (
        f"{base_url}/plugins/viewstorage/viewpagestorage.action?pageId={page_id}"
    )
    api_url = f"{base_url}/rest/api/content/{page_id}"

    try:
        print(f"Fetching page content for page ID: {page_id}...")
        # Fetch the main page content (HTML)
        storage_response = requests.get(storage_url, cookies=cookies)
        storage_response.raise_for_status()  # Raises an exception for bad status codes (4xx or 5xx)
        html_content = storage_response.text
        print("✔️ Content fetched successfully.")

        print("Fetching page metadata...")
        # Fetch the page metadata (JSON for title and author)
        api_response = requests.get(api_url, cookies=cookies)
        api_response.raise_for_status()
        metadata = api_response.json()
        print("✔️ Metadata fetched successfully.")

        title = metadata.get("title", f"Page {page_id}")
        # Safely navigate the nested JSON for the author's username
        username = (
            metadata.get("history", {}).get("createdBy", {}).get("username", "Unknown")
        )

        return html_content, title, username

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401 or e.response.status_code == 403:
            print(
                f"❌ Error: Authentication failed ({e.response.status_code}). Please check your cookie values and permissions."
            )
        elif e.response.status_code == 404:
            print(
                f"❌ Error: Page with ID '{page_id}' not found ({e.response.status_code})."
            )
        else:
            print(f"❌ An HTTP error occurred: {e}")
        return None, None, None
    except requests.exceptions.RequestException as e:
        print(f"❌ A network error occurred: {e}")
        return None, None, None


def download_attachment(page_id, filename):
    """
    Downloads an attachment from Confluence to a local folder.

    Args:
        page_id (str): The Confluence page ID.
        filename (str): The attachment filename.
        dest_folder (str): The destination folder (default: 'tmp').

    Returns:
        str: The local file path if successful, None otherwise.
    """
    url = f"https://sync.hudlnet.com/download/attachments/{page_id}/{filename}"
    dest_folder = "tmp"
    os.makedirs(dest_folder, exist_ok=True)
    local_path = os.path.join(dest_folder, filename)

    aws_cookie = os.getenv("AWSELB_COOKIE")
    seraph_cookie = os.getenv("SERAPH_COOKIE")
    if not all([aws_cookie, seraph_cookie]):
        print("❌ Error: Missing required environment variables for download.")
        return None

    cookies = {
        "AWSELBAuthSessionCookie-0": aws_cookie,
        "seraph.confluence": seraph_cookie,
    }

    try:
        response = requests.get(url, cookies=cookies, stream=True)
        response.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"✔️ Downloaded '{filename}' to '{local_path}'")
        return local_path  # Always return the local file path on success
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to download '{filename}': {e}")
        return None


def upload_to_slack(file_path):
    """
    Uploads a file to a Slack channel.

    Args:
        file_path (str): The path to the file to upload.
        slack_bot_token (str): The Slack bot token for authentication.

    Returns:
        dict: The response from the Slack API.
    """
    client = WebClient(token=SLACK_BOT_TOKEN)
    try:
        uploadUrlResponse = client.files_getUploadURLExternal(
            filename=os.path.basename(file_path), length=os.path.getsize(file_path)
        )
        upload_url = uploadUrlResponse["upload_url"]
        file_id = uploadUrlResponse["file_id"]
        print(f"UploadUrl: {upload_url}, File ID: {file_id}")
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f)}
            response = requests.post(upload_url, files=files)
            if response.status_code == 200:
                print("✔️ File uploaded to Slack successfully.")
                complete_response = client.files_completeUploadExternal(
                    files=[{"id": file_id, "title": os.path.basename(file_path)}]
                )
                print(f"✔️ File completed upload: {complete_response}")
                return complete_response["url_private"]
            else:
                print(f"❌ Slack upload failed: {response.status_code} {response.text}")
                return None

    except Exception as e:
        print(f"❌ Failed to upload file to Slack: {e}")
        return None


# --- Conversion Logic ---


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
        return TAG_MAPPINGS[node.name](node, process_node)
    return "".join(process_node(child) for child in node.children)


def handle_children(node, processor):
    return "".join(processor(child) for child in node.children)


def handle_p(node, processor):
    content = handle_children(node, processor).strip()
    if not content or (node.find("br") and len(node.get_text(strip=True)) == 0):
        return ""
    return content + "\n\n"


def handle_h(level):
    def handler(node, processor):
        content = handle_children(node, processor).strip()
        return f"{'#' * level} {content}\n\n"

    return handler


def handle_em(node, processor):
    """Handles <em> and <i> tags, moving leading/trailing spaces outside the formatting."""
    content = handle_children(node, processor)
    leading_whitespace = content[: len(content) - len(content.lstrip())]
    trailing_whitespace = content[len(content.rstrip()) :]
    core_text = content.strip()
    if not core_text:
        return content  # Return original content if it's all whitespace
    return f"{leading_whitespace}_{core_text}_{trailing_whitespace}"


def handle_strong(node, processor):
    """Handles <strong> and <b> tags, moving leading/trailing spaces outside the formatting."""
    content = handle_children(node, processor)
    leading_whitespace = content[: len(content) - len(content.lstrip())]
    trailing_whitespace = content[len(content.rstrip()) :]
    core_text = content.strip()
    if not core_text:
        return content  # Return original content if it's all whitespace
    # Use single asterisks for Slack's bold format
    return f"{leading_whitespace}**{core_text}**{trailing_whitespace}"


def handle_a(node, processor):
    """Handles <a> tags for standard Markdown links."""
    text = handle_children(node, processor).strip()
    href = node.get("href", "")
    # Handle Confluence relative links
    if href.startswith("/"):
        href = "https://sync.hudlnet.com" + href
    if not text:
        return href
    # Use standard Markdown link format
    return f"[{text}]({href})" if href else text


def handle_li(node, processor):
    return f"* {handle_children(node, processor).strip()}\n"


def handle_br(node, processor):
    return "\n"


def handle_confluence_macro(node, processor):
    macro_name = node.get("ac:name")
    if macro_name in CONFLUENCE_MACRO_MAPPINGS:
        return CONFLUENCE_MACRO_MAPPINGS[macro_name](node, processor)
    return handle_children(node, processor)


def handle_info_note_macro(node, processor):
    """Handles 'info'/'note' macros, using blockquote formatting and ensuring only a single blank line between paragraphs in output."""
    title_node = node.find("ac:parameter", {"ac:name": "title"})
    title = title_node.get_text(strip=True) if title_node else ""
    body_node = node.find("ac:rich-text-body")

    output_parts = []
    blockquote_text_parts = [f"**{title}**"] if title else []

    if not body_node:
        if blockquote_text_parts:
            return "> " + "\n> ".join(blockquote_text_parts) + "\n\n"
        return ""

    for child in body_node.children:
        is_code_macro = (
            hasattr(child, "name")
            and child.name == "ac:structured-macro"
            and child.get("ac:name") == "code"
        )
        if is_code_macro:
            if blockquote_text_parts:
                full_text = "\n".join(blockquote_text_parts).strip()
                # Collapse multiple blank lines to one
                full_text = re.sub(r"(\n\s*){2,}", "\n\n", full_text)
                output_parts.append("> " + full_text.replace("\n", "\n> "))
                blockquote_text_parts = []
            code_markdown = processor(child)
            if code_markdown:
                output_parts.append(code_markdown)
        else:
            child_markdown = processor(child)
            if child_markdown:
                blockquote_text_parts.append(child_markdown)

    if blockquote_text_parts:
        full_text = "\n".join(blockquote_text_parts).strip()
        full_text = re.sub(r"(\n\s*){2,}", "\n\n", full_text)
        output_parts.append("> " + full_text.replace("\n", "\n> "))

    # Join with a single blank line between sections, and collapse 3+ newlines to 2 in the whole block
    return (
        re.sub(r"(\n\s*){3,}", "\n\n", "\n\n".join(filter(None, output_parts))) + "\n\n"
    )


def handle_code_macro(node, processor):
    """Handles Confluence 'code' macros."""
    body_node = node.find("ac:plain-text-body")
    if not body_node:
        return ""

    # After pre-processing, the text is safe to get directly.
    # We unescape it to restore original characters like '<', '>', '&'.
    code_content = html.unescape(body_node.get_text(strip=True))

    lang_param = node.find("ac:parameter", {"ac:name": "language"})
    lang = lang_param.get_text(strip=True) if lang_param else ""

    if not code_content:
        return ""

    return f"```{lang}\n{code_content}\n```\n\n"


def handle_image(node, processor):
    """Handles Confluence image macros."""
    attachment_node = node.find("ri:attachment")
    if not attachment_node:
        return ""

    image_filename = attachment_node.get("ri:filename")
    if not image_filename:
        return ""

    file_path = download_attachment(PAGE_ID, image_filename)
    slack_file_url = upload_to_slack(file_path=file_path)

    return f"![{image_filename}]({slack_file_url})\n\n"


def handle_multimedia_macro(node, processor):
    """Handles Confluence multimedia macros."""
    attachment_node = node.find("ri:attachment")
    if not attachment_node:
        return ""

    multimedia_filename = attachment_node.get("ri:filename")
    if not multimedia_filename:
        return ""

    print(f"Downloading attachment: {multimedia_filename}")

    file_path = download_attachment(PAGE_ID, multimedia_filename)
    slack_file_url = upload_to_slack(file_path=file_path)

    return f"![{multimedia_filename}]({slack_file_url})\n\n"


# --- Mappings ---

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
CONFLUENCE_MACRO_MAPPINGS = {
    "info": handle_info_note_macro,
    "note": handle_info_note_macro,
    "code": handle_code_macro,
    "multimedia": handle_multimedia_macro,
}


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

# Global variable to hold the page ID
PAGE_ID = None
SLACK_BOT_TOKEN = None


def main():
    global PAGE_ID, SLACK_BOT_TOKEN
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
    PAGE_ID = args.page_id
    SLACK_BOT_TOKEN = args.slack_bot_token

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
    html_content, title, username = fetch_confluence_data(args.page_id, cookies)
    if html_content is None:
        return  # Exit if fetching failed

    # Perform the conversion
    print("Converting HTML to Markdown...")
    body_markdown = convert_confluence_html_to_markdown(html_content)
    print("✔️ Conversion complete.")

    # Create two versions of the markdown content
    markdown_for_payload = f"_Original Author: {username}_\n\n{body_markdown}"
    markdown_for_file = f"# {title}\n\n{markdown_for_payload}"

    # Create Output Directory and Filenames
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    base_filename = sanitize_filename(title)
    md_output_path = os.path.join(output_dir, f"{base_filename}.md")
    json_output_path = os.path.join(output_dir, f"{base_filename}_payload.json")

    # Write the Markdown File (with the title)
    with open(md_output_path, "w", encoding="utf-8") as f:
        f.write(markdown_for_file)
    print(f"✔️ Markdown file saved to: '{md_output_path}'")

    # Build and Write the JSON Payload File
    # The title is a top-level property, and the markdown does not contain the title.
    payload = {
        "channel_id": args.channel_id,
        "title": title,
        "document_content": {"type": "markdown", "markdown": markdown_for_payload},
    }
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"✔️ Slack API JSON payload saved to: '{json_output_path}'")


if __name__ == "__main__":
    main()

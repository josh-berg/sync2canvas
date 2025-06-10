import re
import os
import json
import argparse

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
    return f"_{handle_children(node, processor).strip()}_"


def handle_strong(node, processor):
    return f"**{handle_children(node, processor).strip()}**"


def handle_a(node, processor):
    text = handle_children(node, processor).strip()
    href = node.get("href", "")
    if not text:
        return href
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
    title = (
        node.find("ac:parameter", {"ac:name": "title"}).get_text(strip=True)
        if node.find("ac:parameter", {"ac:name": "title"})
        else ""
    )
    body_node = node.find("ac:rich-text-body")
    output_parts, blockquote_text_parts = [], [f"**{title}**\n"] if title else []
    if not body_node:
        return (
            f'> {"".join(blockquote_text_parts)}\n\n' if blockquote_text_parts else ""
        )
    for child in body_node.children:
        is_code_macro = (
            hasattr(child, "name")
            and child.name == "ac:structured-macro"
            and child.get("ac:name") == "code"
        )
        if is_code_macro:
            if blockquote_text_parts:
                full_text = "\n".join(blockquote_text_parts).strip()
                output_parts.append("> " + full_text.replace("\n", "\n> "))
                blockquote_text_parts = []
            code_markdown = processor(child).strip()
            if code_markdown:
                output_parts.append(code_markdown)
        else:
            child_markdown = processor(child).strip()
            if child_markdown:
                blockquote_text_parts.append(child_markdown)
    if blockquote_text_parts:
        full_text = "\n".join(blockquote_text_parts).strip()
        output_parts.append("> " + full_text.replace("\n", "\n> "))
    return "\n\n".join(filter(None, output_parts)) + "\n\n"


def handle_code_macro(node, processor):
    body_node = node.find("ac:plain-text-body")
    if not body_node:
        return ""
    code_content = "".join(
        str(c) for c in body_node.contents if isinstance(c, CData)
    ).strip()
    lang_param = node.find("ac:parameter", {"ac:name": "language"})
    lang = lang_param.get_text(strip=True) if lang_param else ""
    return f"```{lang}\n{code_content}\n```\n\n"


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
    "ac:structured-macro": handle_confluence_macro,
}
CONFLUENCE_MACRO_MAPPINGS = {
    "info": handle_info_note_macro,
    "note": handle_info_note_macro,
    "code": handle_code_macro,
}


def convert_confluence_html_to_markdown(html_content):
    soup = BeautifulSoup(html_content, "lxml")
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
    args = parser.parse_args()

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

    # Prepend metadata to the final markdown
    final_markdown = f"_Original Author: {username}_\n\n# \n{body_markdown}"
    print("✔️ Conversion complete.")

    # Create Output Directory and Filenames
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    base_filename = sanitize_filename(title)
    md_output_path = os.path.join(output_dir, f"{base_filename}.md")
    json_output_path = os.path.join(output_dir, f"{base_filename}_payload.json")

    # Write the Markdown File
    with open(md_output_path, "w", encoding="utf-8") as f:
        f.write(final_markdown)
    print(f"✔️ Markdown file saved to: '{md_output_path}'")

    # Build and Write the JSON Payload File
    payload = {
        "title": title,
        "channel_id": args.channel_id,
        "document_content": {"type": "markdown", "markdown": final_markdown},
    }
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"✔️ Slack API JSON payload saved to: '{json_output_path}'")


if __name__ == "__main__":
    main()

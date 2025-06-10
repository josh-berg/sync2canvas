import re
import os
import json
import argparse
from bs4 import BeautifulSoup, NavigableString, CData


def process_node(node):
    """
    Recursively processes a BeautifulSoup node and its children,
    converting them to Markdown based on defined mappings.
    """
    # If it's a string, just return it after cleaning.
    if isinstance(node, NavigableString):
        # For CDATA sections (like in code blocks), we don't want to escape them.
        # For regular strings, we can do some minor cleaning.
        if isinstance(node, CData):
            return node
        text = str(node)
        # Confluence often adds non-breaking spaces; replace them.
        text = text.replace("\xa0", " ")
        # Collapse multiple whitespace characters into a single space.
        text = re.sub(r"\s+", " ", text)
        return text

    # If it's a tag, look up its mapping.
    if node.name in TAG_MAPPINGS:
        # Pass the node and the processor to the mapping function.
        return TAG_MAPPINGS[node.name](node, process_node)

    # If no mapping exists for the tag, just process its children.
    # This effectively ignores tags like <span> or <div> while keeping their content.
    return "".join(process_node(child) for child in node.children)


def handle_children(node, processor):
    """A helper function to process all children of a node and join the results."""
    return "".join(processor(child) for child in node.children)


def handle_p(node, processor):
    """Handles <p> tags. Adds two newlines for paragraph breaks."""
    content = handle_children(node, processor).strip()
    # Ignore paragraphs that are empty or just contain a line break.
    if not content or node.find("br") and len(node.get_text(strip=True)) == 0:
        return ""
    return content + "\n\n"


def handle_h(level):
    """A factory function to create handlers for <h1>, <h2>, etc."""

    def handler(node, processor):
        content = handle_children(node, processor).strip()
        return f"{'#' * level} {content}\n\n"

    return handler


def handle_em(node, processor):
    """Handles <em> and <i> tags for italics."""
    content = handle_children(node, processor).strip()
    return f"_{content}_"


def handle_strong(node, processor):
    """Handles <strong> and <b> tags for bold."""
    content = handle_children(node, processor).strip()
    return f"*{content}*"


def handle_a(node, processor):
    """Handles <a> tags for links."""
    text = handle_children(node, processor).strip()
    href = node.get("href", "")
    if not text:
        return href
    return f"<{href}|{text}>" if href else text


def handle_li(node, processor):
    """Handles <li> tags."""
    content = handle_children(node, processor).strip()
    return f"* {content}\n"


def handle_br(node, processor):
    """Handles <br> tags."""
    return "\n"


def handle_confluence_macro(node, processor):
    """
    Handles the complex <ac:structured-macro> tag by dispatching
    to more specific handlers based on the macro's name.
    """
    macro_name = node.get("ac:name")
    if macro_name in CONFLUENCE_MACRO_MAPPINGS:
        return CONFLUENCE_MACRO_MAPPINGS[macro_name](node, processor)
    # If the macro is unknown, process its contents to not lose information.
    return handle_children(node, processor)


def handle_info_note_macro(node, processor):
    """
    Handles Confluence 'info' and 'note' macros.
    Formats them as a Slack blockquote with a bolded title.
    It "breaks out" of the blockquote for nested code blocks, as Slack does not support them.
    """
    title_node = node.find("ac:parameter", {"ac:name": "title"})
    title = title_node.get_text(strip=True) if title_node else ""

    body_node = node.find("ac:rich-text-body")

    output_parts = []

    # Start building the initial blockquote content (title and text)
    blockquote_text_parts = []
    if title:
        blockquote_text_parts.append(f"*{title}*")

    if not body_node:
        if blockquote_text_parts:
            return "> " + "".join(blockquote_text_parts) + "\n\n"
        return ""

    # Iterate through child elements to separate blockquote content from code blocks
    for child in body_node.children:
        is_code_macro = (
            hasattr(child, "name")
            and child.name == "ac:structured-macro"
            and child.get("ac:name") == "code"
        )

        if is_code_macro:
            # 1. Finalize and append any pending blockquote text
            if blockquote_text_parts:
                full_text = "\n".join(blockquote_text_parts).strip()
                output_parts.append("> " + full_text.replace("\n", "\n> "))
                blockquote_text_parts = []  # Reset

            # 2. Process and append the code block without a blockquote
            code_markdown = processor(child).strip()
            if code_markdown:
                output_parts.append(code_markdown)
        else:
            # It's not a code macro, so add its processed content for later blockquoting
            child_markdown = processor(child).strip()
            if child_markdown:
                blockquote_text_parts.append(child_markdown)

    # After the loop, append any remaining blockquote text
    if blockquote_text_parts:
        full_text = "\n".join(blockquote_text_parts).strip()
        output_parts.append("> " + full_text.replace("\n", "\n> "))

    # Join all the parts (blockquotes, code blocks) with proper spacing
    return "\n\n".join(part for part in output_parts if part) + "\n\n"


def handle_code_macro(node, processor):
    """
    Handles Confluence 'code' macros.
    Formats them as a Markdown code block.
    """
    body_node = node.find("ac:plain-text-body")
    if not body_node:
        return ""

    code_content = "".join(
        str(c) for c in body_node.contents if isinstance(c, CData)
    ).strip()

    # Check for a language parameter, though not present in the example.
    lang_param = node.find("ac:parameter", {"ac:name": "language"})
    lang = lang_param.get_text(strip=True) if lang_param else ""

    return f"```{lang}\n{code_content}\n```\n\n"


# ==============================================================================
# ==                           MAPPING DEFINITIONS                          ==
# ==============================================================================
#
# This is the main configuration area.
# To add a new HTML tag, add a key-value pair to TAG_MAPPINGS.
# The key is the tag name (e.g., 'div').
# The value is the function that will handle its conversion.
#
# To handle a new Confluence macro, add an entry to
# CONFLUENCE_MACRO_MAPPINGS.
#
# ==============================================================================

TAG_MAPPINGS = {
    # --- Block Level Tags ---
    "p": handle_p,
    "h1": handle_h(1),
    "h2": handle_h(2),
    "h3": handle_h(3),
    "h4": handle_h(3),  # Mapped to ### for Slack Canvas compatibility
    "h5": handle_h(3),  # Mapped to ### for Slack Canvas compatibility
    "h6": handle_h(3),  # Mapped to ### for Slack Canvas compatibility
    "li": handle_li,
    "ul": handle_children,  # ul/ol tags don't get special chars, the li does
    "ol": handle_children,
    "br": handle_br,
    # --- Inline Tags ---
    "a": handle_a,
    "em": handle_em,
    "i": handle_em,
    "strong": handle_strong,
    "b": handle_strong,
    # --- Confluence Specific Tags ---
    "ac:structured-macro": handle_confluence_macro,
}

# This dictionary maps Confluence macro names to their handler functions.
CONFLUENCE_MACRO_MAPPINGS = {
    "info": handle_info_note_macro,
    "note": handle_info_note_macro,
    "code": handle_code_macro,
    # Add other macros here, e.g., 'warning', 'tip'
}


def convert_confluence_html_to_markdown(html_content):
    """
    Main function to convert a Confluence HTML string to Slack Markdown.

    Args:
        html_content (str): The raw HTML from Confluence.

    Returns:
        str: The converted Markdown string.
    """
    # Use the 'lxml' parser for flexibility with HTML fragments.
    soup = BeautifulSoup(html_content, "lxml")

    # Process the entire body of the parsed document
    markdown_output = process_node(soup.body or soup)

    # Final cleanup: Ensure there aren't more than two consecutive newlines
    markdown_output = re.sub(r"\n{3,}", "\n\n", markdown_output)

    return markdown_output.strip()


# ==============================================================================
# ==                              SCRIPT EXECUTION                            ==
# ==============================================================================


def main():
    """
    Main execution function that sets up argument parsing, file I/O,
    and calls the conversion logic.
    """
    # --- Setup Argument Parser ---
    parser = argparse.ArgumentParser(
        description="Converts a Confluence HTML export to Slack-compatible Markdown and a JSON API payload."
    )
    parser.add_argument(
        "input_file", help="Path to the input file containing the Confluence HTML."
    )
    parser.add_argument(
        "-c",
        "--channel-id",
        required=True,
        help="The Slack channel ID where the canvas will be created (e.g., C07317JTXCP).",
    )
    args = parser.parse_args()

    # --- Read Input File ---
    try:
        with open(args.input_file, "r", encoding="utf-8") as f:
            html_content = f.read()
    except FileNotFoundError:
        print(f"Error: Input file not found at '{args.input_file}'")
        return
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    # --- Perform the conversion ---
    print(f"Converting '{args.input_file}'...")
    markdown_result = convert_confluence_html_to_markdown(html_content)

    # --- Create Output Directory and Filenames ---
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    base_filename = os.path.basename(args.input_file)
    filename_without_ext = os.path.splitext(base_filename)[0]

    md_output_path = os.path.join(output_dir, f"{filename_without_ext}.md")
    json_output_path = os.path.join(output_dir, f"{filename_without_ext}_payload.json")

    # --- Write the Markdown File ---
    try:
        with open(md_output_path, "w", encoding="utf-8") as f:
            f.write(markdown_result)
        print(f"✔️ Markdown file saved to: '{md_output_path}'")
    except Exception as e:
        print(f"❌ Error writing Markdown file: {e}")
        return

    # --- Build and Write the JSON Payload File ---
    payload = {
        "channel_id": args.channel_id,
        "document_content": {"type": "markdown", "markdown": markdown_result},
    }

    try:
        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"✔️ Slack API JSON payload saved to: '{json_output_path}'")
    except Exception as e:
        print(f"❌ Error writing JSON payload file: {e}")


if __name__ == "__main__":
    main()

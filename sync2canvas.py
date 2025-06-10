import re
import os
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
            print("CDATA Node:", node)
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
        print("Mapped Node:", node)
        return TAG_MAPPINGS[node.name](node, process_node)

    # If no mapping exists for the tag, just process its children.
    # This effectively ignores tags like <span> or <div> while keeping their content.
    print("Unknown Node:", node.name)
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
    """
    title_node = node.find("ac:parameter", {"ac:name": "title"})
    title = title_node.get_text(strip=True) if title_node else ""

    body_node = node.find("ac:rich-text-body")
    body_content = ""
    if body_node:
        # We need to process the children of the body node
        body_content = handle_children(body_node, processor).strip()

    # Format as a Slack blockquote
    # Note: Slack's blockquote (`>`) applies to the whole block.
    # We create the title and then indent the body content.
    formatted_str = ""
    if title:
        formatted_str += f"> *{title}*\n"

    # Add each line of the body content with the blockquote prefix.
    # This ensures multi-paragraph content inside the macro is quoted correctly.
    if body_content:
        indented_body = "\n".join(
            [f"> {line}" for line in body_content.strip().split("\n")]
        )
        formatted_str += indented_body

    return formatted_str + "\n\n"


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
    "h4": handle_h(4),
    "h5": handle_h(5),
    "h6": handle_h(6),
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
    # The 'xml' parser is too strict and fails on this input.
    soup = BeautifulSoup(html_content, "lxml")

    # Process the entire body of the parsed document
    markdown_output = process_node(soup)

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
        description="Converts a Confluence HTML export file (.txt or .html) to Slack-compatible Markdown."
    )
    parser.add_argument(
        "input_file", help="Path to the input file containing the Confluence HTML."
    )
    args = parser.parse_args()

    # --- Read Input File ---
    try:
        with open(args.input_file, "r", encoding="utf-8") as f:
            html_content = f.read()
    except FileNotFoundError:
        print(f"Error: Input file not found at '{args.input_file}'")
        return  # Exit the function
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    # --- Perform the conversion ---
    print(f"Converting '{args.input_file}'...")
    markdown_result = convert_confluence_html_to_markdown(html_content)

    # --- Write to Output File ---
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    base_filename = os.path.basename(args.input_file)
    filename_without_ext = os.path.splitext(base_filename)[0]
    output_filename = f"{filename_without_ext}.md"
    output_path = os.path.join(output_dir, output_filename)

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(markdown_result)
        print(f"Successfully converted.")
        print(f"Markdown output saved to: '{output_path}'")
    except Exception as e:
        print(f"Error writing to output file: {e}")


if __name__ == "__main__":
    main()

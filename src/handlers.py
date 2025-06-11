import html
from networkUtils import download_attachment, upload_to_slack
import globals

from fileUtils import delete_file


def handle_children(node, processor):
    return "".join(processor(child) for child in node.children)


def handle_p(node, processor):
    content = handle_children(node, processor)
    # Only treat as empty if content is truly empty (not just whitespace or block-level content)
    has_block = any(
        child.name in ("ac:structured-macro", "ac:image")
        for child in node.descendants
        if hasattr(child, "name")
    )
    if not content.strip() and not has_block:
        return ""
    # Remove the 'br' check: always output if there is block-level content
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

    file_path = download_attachment(image_filename)
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

    file_path = download_attachment(multimedia_filename)
    slack_file_url = upload_to_slack(file_path=file_path)

    return f"![{multimedia_filename}]({slack_file_url})\n\n"


def handle_jira_macro(node, processor):
    """Handles Confluence JIRA macros."""
    jira_issue_key = None
    for param in node.find_all("ac:parameter"):
        if param.get("ac:name") == "key":
            jira_issue_key = param.get_text(strip=True)
            break
    if not jira_issue_key:
        return ""

    # Format the JIRA issue link
    jira_url = f"https://hudl-jira.atlassian.net/browse/{jira_issue_key}"
    return f"[{jira_issue_key}]({jira_url})\n\n"


def handle_info_note_macro(node, processor):
    """Handles 'info'/'note' macros, wrapping content in callout markers and using standard parsing for inner content. Adds an index to each callout."""
    title_node = node.find("ac:parameter", {"ac:name": "title"})
    title = title_node.get_text(strip=True) if title_node else ""
    body_node = node.find("ac:rich-text-body")

    current_callout = globals.CALLOUT_COUNTER_INDEX
    globals.CALLOUT_COUNTER_INDEX += 1

    output_parts = [f"===========START CALLOUT {current_callout}==========\n"]
    if title:
        output_parts.append(f"**{title}**\n")
    if body_node:
        # Standard parsing for everything inside the macro
        body_content = handle_children(body_node, processor).strip()
        if body_content:
            output_parts.append(body_content)
    output_parts.append(f"\n===========END CALLOUT {current_callout}==========\n")
    return "\n".join(output_parts) + "\n\n"


def handle_table(node, processor):
    all_rows = []
    th_first_col_every_row = True

    # Find all rows (including those inside <tbody>)
    for tbody in node.find_all("tbody"):
        for tr in tbody.find_all("tr", recursive=False):
            cells = []
            cell_tags = []
            for cell in tr.find_all(["th", "td"], recursive=False):
                cell_content = handle_children(cell, processor).strip()
                cell_content = cell_content.replace("\n", " ").strip()
                colspan = int(cell.get("colspan", 1))
                cells.append(cell_content)
                cell_tags.append(cell.name)
                for _ in range(colspan - 1):
                    cells.append("")
                    cell_tags.append(cell.name)
            all_rows.append((cells, cell_tags))

    if not all_rows:
        return ""

    # Check if every row's first cell is a th
    for _, tags in all_rows:
        if not tags or tags[0] != "th":
            th_first_col_every_row = False
            break

    # Always use the first row as header row
    header_cells, header_tags = all_rows[0]
    output = []
    # Bold the first column in the header row if needed
    if th_first_col_every_row:
        header_cells_fmt = [f"**{header_cells[0]}**"] + header_cells[1:]
    else:
        header_cells_fmt = header_cells
    output.append("| " + " | ".join(header_cells_fmt) + " |")
    output.append("|" + "|".join([" --- " for _ in header_cells_fmt]) + "|")

    # Render the rest of the rows
    for cells, tags in all_rows[1:]:
        # Pad row if short
        cells = cells + ["" for _ in range(len(header_cells_fmt) - len(cells))]
        if th_first_col_every_row:
            row_fmt = [f"**{cells[0]}**"] + cells[1:]
        else:
            row_fmt = cells
        output.append("| " + " | ".join(row_fmt) + " |")
    return "\n".join(output) + "\n\n"


def handle_ac_link(node, processor):
    # If this is a user link, show a placeholder or userkey
    user_node = node.find("ri:user")
    if user_node:
        return handle_ri_user(node, processor)
    # Otherwise, process as normal
    return handle_children(node, processor)


def handle_ri_user(node, processor):
    user_node = node.find("ri:user")
    userkey = user_node.get("ri:userkey") if user_node else None
    # TODO: Handle userkey lookup or mapping if needed
    return f"@{userkey}" if userkey else "@unknown_user"


def handle_time(node, processor):
    datetime_value = node.get("datetime")
    return datetime_value if datetime_value else ""


def handle_task(node, processor):
    status_node = node.find("ac:task-status")
    body_node = node.find("ac:task-body")

    status = status_node.get_text(strip=True) if status_node else ""
    body = body_node.get_text(strip=True) if body_node else ""

    checkbox = "x" if status == "complete" else " "
    return f"- [{checkbox}] {body}\n"


CONFLUENCE_MACRO_MAPPINGS = {
    "info": handle_info_note_macro,
    "note": handle_info_note_macro,
    "code": handle_code_macro,
    "multimedia": handle_multimedia_macro,
    "jira": handle_jira_macro,
}

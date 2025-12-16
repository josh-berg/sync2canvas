import os
import requests
from slack_sdk import WebClient
import globals

from pathUtils import (
    get_sync_attachment_url,
    get_sync_content_api_url,
    get_sync_page_storage_url,
    get_sync_user_api_url,
)


def fetch_confluence_data(cookies):
    storage_url = get_sync_page_storage_url(globals.PAGE_ID)
    api_url = get_sync_content_api_url(globals.PAGE_ID)

    try:
        print(f"🌐 Fetching page content for page ID: {globals.PAGE_ID}...")
        # Fetch the main page content (HTML)
        storage_response = requests.get(storage_url, cookies=cookies)
        storage_response.raise_for_status()  # Raises an exception for bad status codes (4xx or 5xx)
        html_content = storage_response.text
        print("✅ Content fetched successfully.")

        print("📰 Fetching page metadata...")
        # Fetch the page metadata (JSON for title and author)
        api_response = requests.get(api_url, cookies=cookies)
        api_response.raise_for_status()
        metadata = api_response.json()
        print("✅ Metadata fetched successfully.")

        title = metadata.get("title", f"Page {globals.PAGE_ID}")
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
                f"❌ Error: Page with ID '{globals.PAGE_ID}' not found ({e.response.status_code})."
            )
        else:
            print(f"❌ An HTTP error occurred: {e}")
        return None, None, None
    except requests.exceptions.RequestException as e:
        print(f"❌ A network error occurred: {e}")
        return None, None, None


def download_attachment(filename):
    url = get_sync_attachment_url(globals.PAGE_ID, filename)
    dest_folder = "tmp"
    os.makedirs(dest_folder, exist_ok=True)
    local_path = os.path.join(dest_folder, filename)

    aws_cookie = os.getenv("AWSELB_COOKIE")
    jsessionid = os.getenv("JSESSIONID")
    if not all([aws_cookie, jsessionid]):
        print("❌ Error: Missing required environment variables for download.")
        return None

    cookies = {
        "AWSELBAuthSessionCookie-0": aws_cookie,
        "seraph.confluence": jsessionid,
    }

    try:
        response = requests.get(url, cookies=cookies, stream=True)
        response.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"🪣 Downloaded '{filename}' to '{local_path}'")
        return local_path  # Always return the local file path on success
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to download '{filename}': {e}")
        return None


def upload_to_slack(file_path):
    client = WebClient(token=globals.SLACK_BOT_TOKEN)
    try:
        uploadUrlResponse = client.files_getUploadURLExternal(
            filename=os.path.basename(file_path), length=os.path.getsize(file_path)
        )
        upload_url = uploadUrlResponse["upload_url"]
        file_id = uploadUrlResponse["file_id"]
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f)}
            response = requests.post(upload_url, files=files)
            if response.status_code == 200:
                print("☁️ File uploaded to Slack successfully.")
                complete_response = client.files_completeUploadExternal(
                    files=[{"id": file_id, "title": os.path.basename(file_path)}]
                )
                return complete_response["files"][0]["permalink"]
            else:
                print(f"❌ Slack upload failed: {response.status_code} {response.text}")
                return None

    except Exception as e:
        print(f"❌ Failed to upload file to Slack: {e}")
        return None


def create_slack_canvas(channel_id, title, markdown_content):
    client = WebClient(token=globals.SLACK_BOT_TOKEN)
    try:
        response = client.canvases_create(
            title=title,
            channel_id=channel_id,
            document_content={"type": "markdown", "markdown": markdown_content},
        )
        canvas_id = response["canvas_id"]
        print(
            f"🖼️ Canvas created in Slack channel. View Canvas: https://hudl.slack.com/docs/T025Q1R55/{canvas_id}"
        )
    except Exception as e:
        print(f"❌ Failed to create Slack canvas: {e}")
        return None


def fetch_user_username(userkey):
    user_api_url = get_sync_user_api_url(userkey)
    aws_cookie = os.getenv("AWSELB_COOKIE")
    jsessionid = os.getenv("JSESSIONID")
    if not all([aws_cookie, jsessionid]):
        print("❌ Error: Missing required environment variables for user fetch.")
        return None

    cookies = {
        "AWSELBAuthSessionCookie-0": aws_cookie,
        "seraph.confluence": jsessionid,
    }

    try:
        response = requests.get(user_api_url, cookies=cookies)
        response.raise_for_status()
        user_data = response.json()
        return user_data.get("username", "Unknown User")
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to fetch user data: {e}")
        return None


def fetch_slack_user_by_email(email):
    client = WebClient(token=globals.SLACK_BOT_TOKEN)
    try:
        response = client.users_lookupByEmail(email=email)
        if response["ok"]:
            print(f"🔍 Slack user found for {email} ({response['user']['id']})")
            return response["user"]["id"]
        else:
            print(f"🤷 Slack user not found for {email}.")
            return None
    except Exception as e:
        return None

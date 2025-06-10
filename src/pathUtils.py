BASE_SYNC_URL = "https://sync.hudlnet.com"
SYNC_PAGE_STORAGE_PATH = "/plugins/viewstorage/viewpagestorage.action?pageId="
SYNC_CONTENT_API_PATH = "/rest/api/content/"
SYNC_ATTACHMENT_PATH = "download/attachments/"


def get_sync_page_storage_url(page_id):
    return f"{BASE_SYNC_URL}{SYNC_PAGE_STORAGE_PATH}{page_id}"


def get_sync_content_api_url(page_id):
    return f"{BASE_SYNC_URL}{SYNC_CONTENT_API_PATH}{page_id}"


def get_sync_attachment_url(page_id, filename):
    return f"{BASE_SYNC_URL}/{SYNC_ATTACHMENT_PATH}{page_id}/{filename}"

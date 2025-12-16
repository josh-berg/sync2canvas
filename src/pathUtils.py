SYNC_PAGE_STORAGE_PATH = "/plugins/viewstorage/viewpagestorage.action?pageId="
SYNC_CONTENT_API_PATH = "/rest/api/content/"
SYNC_USER_API_PATH = "/rest/api/user?key="
SYNC_ATTACHMENT_PATH = "download/attachments/"


def get_sync_page_storage_url(base_confluence_url, page_id):
    return f"{base_confluence_url}{SYNC_PAGE_STORAGE_PATH}{page_id}"


def get_sync_content_api_url(base_confluence_url, page_id):
    return f"{base_confluence_url}{SYNC_CONTENT_API_PATH}{page_id}"


def get_sync_attachment_url(base_confluence_url, page_id, filename):
    return f"{base_confluence_url}/{SYNC_ATTACHMENT_PATH}{page_id}/{filename}"


def get_sync_user_api_url(base_confluence_url, userkey):
    return f"{base_confluence_url}{SYNC_USER_API_PATH}{userkey}"

"""Compat shim — storage was migrated from Google Cloud Storage to Cloudflare R2.

All real logic lives in `cloudrun.r2_storage`. This module re-exports the
old names so callers that haven't been updated keep working. New code
should import from `cloudrun.r2_storage` directly.
"""

from cloudrun.r2_storage import (  # noqa: F401
    GCSWorkspace,
    R2Workspace,
    download_file,
    download_files,
    generate_signed_url,
    get_client,
    get_client as get_gcs_client,
    list_files,
    object_exists,
    parse_gcs_uri,
    parse_uri,
    upload_directory,
    upload_file,
)

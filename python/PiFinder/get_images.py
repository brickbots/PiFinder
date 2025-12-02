from PiFinder.object_images.poss_provider import BASE_IMAGE_PATH
from PiFinder.object_images.poss_provider import create_catalog_image_dirs
#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This script runs to fetch
images from AWS
"""

import requests
import os
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from PiFinder.object_images import get_display_image
from PiFinder.db.objects_db import ObjectsDatabase


def check_missing_images() -> List[str]:
    """
    Efficiently check which images need to be fetched by working directly
    with image names from the database instead of creating CompositeObjects.

    Returns list of missing image names.
    """
    objects_db = ObjectsDatabase()
    _, cursor = objects_db.get_conn_cursor()

    # Get all image names directly from object_images table
    cursor.execute(
        "SELECT DISTINCT image_name FROM object_images WHERE image_name != ''"
    )
    image_names = [row["image_name"] for row in cursor.fetchall()]

    missing_images = []
    for image_name in tqdm(image_names, desc="Checking existing images"):
        # Check if POSS image exists (primary check)
        poss_path = (
            f"{BASE_IMAGE_PATH}/{image_name[-1]}/{image_name}_POSS.jpg"
        )
        if not os.path.exists(poss_path):
            missing_images.append(image_name)

    return missing_images


def download_image_from_url(
    session: requests.Session, url: str, file_path: str
) -> Tuple[bool, str]:
    """
    Download a single image using provided session.

    Returns (success, error_message)
    """
    try:
        response = session.get(url, timeout=30)
        if response.status_code == 200:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(response.content)
            return True, ""
        elif response.status_code == 403:
            return False, "Not available (403)"
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, f"Error: {str(e)}"


def fetch_images_for_object(
    session: requests.Session, image_name: str
) -> Tuple[str, bool, List[str]]:
    """
    Fetch both POSS and SDSS images for a given image name.

    Returns (image_name, success, error_messages)
    """
    errors = []
    seq_ones = image_name[-1]  # Last character for directory

    # Download POSS image
    poss_filename = f"{image_name}_POSS.jpg"
    poss_path = f"{BASE_IMAGE_PATH}/{seq_ones}/{poss_filename}"
    poss_url = f"https://ddbeeedxfpnp0.cloudfront.net/catalog_images/{seq_ones}/{poss_filename}"

    poss_success, poss_error = download_image_from_url(session, poss_url, poss_path)
    if not poss_success:
        errors.append(f"POSS: {poss_error}")

    # Download SDSS image
    sdss_filename = f"{image_name}_SDSS.jpg"
    sdss_path = f"{BASE_IMAGE_PATH}/{seq_ones}/{sdss_filename}"
    sdss_url = f"https://ddbeeedxfpnp0.cloudfront.net/catalog_images/{seq_ones}/{sdss_filename}"

    sdss_success, sdss_error = download_image_from_url(session, sdss_url, sdss_path)
    if not sdss_success:
        errors.append(f"SDSS: {sdss_error}")

    # Consider successful if at least one image was downloaded
    overall_success = poss_success or sdss_success

    return image_name, overall_success, errors


def download_images_concurrent(image_names: List[str], max_workers: int = 10) -> None:
    """
    Download images concurrently using ThreadPoolExecutor.

    Args:
        image_names: List of image names to download
        max_workers: Maximum number of concurrent downloads
    """
    if not image_names:
        return

    # Create a session for connection pooling
    session = requests.Session()
    session.headers.update({"User-Agent": "PiFinder-ImageDownloader/1.0"})

    failed_downloads = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all download tasks
        future_to_image = {
            executor.submit(fetch_images_for_object, session, image_name): image_name
            for image_name in image_names
        }

        # Process completed downloads with progress bar
        for future in tqdm(
            as_completed(future_to_image),
            total=len(image_names),
            desc="Downloading images",
        ):
            image_name = future_to_image[future]
            try:
                image_name, success, errors = future.result()
                if not success and errors:
                    failed_downloads.append((image_name, errors))
            except Exception as exc:
                failed_downloads.append((image_name, [f"Exception: {exc}"]))

    # Report failed downloads
    if failed_downloads:
        print(f"\nFailed to download {len(failed_downloads)} objects:")
        for image_name, errors in failed_downloads[:10]:  # Show first 10 failures
            print(f"  {image_name}: {', '.join(errors)}")
        if len(failed_downloads) > 10:
            print(f"  ... and {len(failed_downloads) - 10} more")

    session.close()


def main():
    """
    Main function to check for and download missing catalog images.
    """
    create_catalog_image_dirs()

    print("Checking for missing images...")
    missing_images = check_missing_images()

    if len(missing_images) > 0:
        print(f"Found {len(missing_images)} objects with missing images")
        print("Starting concurrent download...")
        download_images_concurrent(missing_images, max_workers=10)
        print("Download complete!")
    else:
        print("All images already downloaded!")


if __name__ == "__main__":
    main()

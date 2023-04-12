import requests
import sqlite3

from PiFinder import cat_images

def get_catalog_objects():
    conn = sqlite3.connect(cat_images.CATALOG_PATH)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()
    cat_objects = conn.execute(
        f"""
        SELECT * from objects
        order by catalog,sequence
    """
    ).fetchall()
    return cat_objects


def fetch_object_image(catalog_object):
    """
    Check if image exists
    or fetch it.

    Returns image path
    """
    print(f"Fetching image for {catalog_object['catalog']}{catalog_object['sequence']}")

    object_image_path = cat_images.resolve_image_name(catalog_object, "POSS")
    if not os.path.exists(object_image_path):
        # POSS
        image_name = object_image_path.split("/")[-1]
        seq_ones = image_name.split("_")[0][-1]
        s3_url = f"https://ddbeeedxfpnp0.cloudfront.net/catalog_images/{seq_ones}/{image_name}"
        r = requests.get(s3_url
        with open(object_image_path, 'wb') as f:
            f.write(r.content)

        object_image_path = cat_images.resolve_image_name(catalog_object, "SDSS")
        image_name = object_image_path.split("/")[-1]
        seq_ones = image_name.split("_")[0][-1]
        s3_url = f"https://ddbeeedxfpnp0.cloudfront.net/catalog_images/{seq_ones}/{image_name}"
        r = requests.get(s3_url
        with open(object_image_path, 'wb') as f:
            f.write(r.content)

    return True

def main():
    for obj in get_catalog_objects():
        fetch_object_image(obj)

if __name__ == "__main__":
    main()

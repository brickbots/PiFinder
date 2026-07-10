# Convert legacy per-source object images to one sourceless image per object.
# Renames <name>_POSS.jpg / <name>_SDSS.jpg to <name>.jpg (POSS wins when both
# exist; the redundant SDSS file is removed) so the device matches the
# sourceless CDN layout. Idempotent and version-gated by pifinder_post_update.sh.
# See docs/adr/0018-one-object-image-per-object.md.
python /home/pifinder/PiFinder/python/PiFinder/migrations/v2_7_0_sourceless_images.py /home/pifinder/PiFinder_data/catalog_images

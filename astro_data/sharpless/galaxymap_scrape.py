import requests

# Base URL of the pages to be downloaded
base_url = "http://galaxymap.org/cat/list/sharpless/"

# List of page numbers to fetch
page_numbers = [
    1,
    11,
    21,
    31,
    41,
    51,
    61,
    71,
    81,
    91,
    101,
    111,
    121,
    131,
    141,
    151,
    161,
    171,
    181,
    191,
    201,
    211,
    221,
    231,
    241,
    251,
    261,
    271,
    281,
    291,
    301,
    311,
]

# Filename to store the collected contents
output_file = "galaxymap_pages.txt"

# Open the file in write mode to start fresh
with open(output_file, "w") as file:
    for number in page_numbers:
        # Construct the full URL
        url = f"{base_url}{number}"

        # Make the HTTP request to get the content
        try:
            response = requests.get(url)
            response.raise_for_status()  # Raise an error for bad status codes
            # Write the content to file
            file.write(response.text)
            # Optional: add a newline or other separator between contents of different pages
            file.write("\n\n")
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")

print(f"All pages have been collected into {output_file}.")

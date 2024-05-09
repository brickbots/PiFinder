from bs4 import BeautifulSoup
import re
import csv


def clean_text(text):
    """Clean up text by replacing sequences of whitespace characters with a single space."""
    # Replace sequences of whitespace with a single space and trim any leading/trailing whitespace.
    text = re.sub(r"\s+", " ", text, flags=re.UNICODE)
    return text.strip()


def extract_and_write_to_csv(input_file_path, output_csv_path):
    # Read the HTML content from the file
    with open(input_file_path, "r", encoding="utf-8") as file:
        html_content = file.read()

    # Regex to split the content by the start of a typical HTML page structure or divisions
    pages = re.split(
        r'(?=<html>|<div class="item-wrapper")', html_content, flags=re.IGNORECASE
    )

    # Prepare to write to CSV without quoting all fields
    with open(output_csv_path, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Sharpless Index", "Description"])  # Write header

        for page_content in pages:
            if not page_content.strip():
                continue  # Skip any empty result

            # Parse each separated HTML content
            soup = BeautifulSoup(page_content, "lxml")

            # Extract data from this portion of HTML
            entries = soup.find_all("div", class_="item-wrapper")
            for entry in entries:
                try:
                    index = entry.find("h4").get_text(strip=True)[5:]
                    description = entry.find(
                        "div", class_="item-description"
                    ).get_text()
                    description = clean_text(description)
                    # Manually adding quotes to the description only
                    writer.writerow([index, f'"{description}"'])
                except AttributeError:
                    # Skip entries where expected fields are missing
                    continue

    print(f"Data has been extracted and saved to {output_csv_path}")


# Specify the file paths
input_file_path = "galaxymap_pages.txt"
output_csv_path = "galaxymap_descriptions.csv"

# Call the function
extract_and_write_to_csv(input_file_path, output_csv_path)

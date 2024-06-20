import requests
from bs4 import BeautifulSoup
import pandas as pd

url = "https://en.wikipedia.org/wiki/Atlas_of_Peculiar_Galaxies"
response = requests.get(url)
soup = BeautifulSoup(response.content, "html.parser")

data = []

# Locate the table containing the galaxy list
tables = soup.find_all("table", {"class": "wikitable"})
# Iterate through each table and extract data
for table in tables:
    rows = table.find_all("tr")
    print(rows)
    for row in rows[1:]:  # Skip the header row
        cells = row.find_all("td")
        if len(cells) > 1:
            arp_number = cells[0].get_text(strip=True)
            description = cells[1].get_text(strip=True)
            if len(cells) > 2:
                comment = cells[2].get_text(strip=True)
                data.append(
                    {
                        "Arp Number": arp_number,
                        "Description": description,
                        "Comment": comment,
                    }
                )
            else:
                data.append(
                    {
                        "Arp Number": arp_number,
                        "Description": description,
                        "Comment": "",
                    }
                )

df = pd.DataFrame(data)
df.to_csv("arp_galaxies.csv", index=False)

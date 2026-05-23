import csv
import re
import sys
import argparse

def process_text_to_csv(input_file, output_file):
    # Read the input file
    with open(input_file, 'r', encoding='utf-8') as f:
        input_text = f.read()

    # Build a map of P-objects for reference
    p_objects = {}
    p_pattern = re.compile(r'^P\d+\s+([^\s]+)\s+')

    for line in input_text.split('\n'):
        match = p_pattern.match(line.strip())
        if match:
            designation = match.group(1)
            p_number = f"P{line.strip().split()[0][1:]}"  # Extract P-number
            p_objects[designation] = p_number

    # Process all objects
    objects = []
    current_object = None

    for line in input_text.split('\n'):
        line = line.strip()

        # Skip empty lines, section headers, and P-object listings
        if not line or 'Constellation:' in line or line.startswith('P') or 'The Guy Pirro' in line:
            continue

        # Parse object entries
        # Match pattern: designation(s) + type + optional comments
        parts = line.split()
        if len(parts) >= 2:
            # Handle potential multi-word object designations
            if parts[0] in ['IC', 'NGC', 'Messier', 'Caldwell']:
                # Find where the type begins (after the designation)
                i = 1
                while i < len(parts) and parts[i][0].isdigit():
                    i += 1

                designation = ' '.join(parts[:i])
                type_and_comments = parts[i:]

                # Find where the type ends and comments begin
                type_end = 1  # At least one word for type
                while (type_end < len(type_and_comments) and
                       type_and_comments[type_end].lower() in ['cluster', 'nebula', 'galaxy', 'remnant']):
                    type_end += 1

                obj_type = ' '.join(type_and_comments[:type_end])
                comments = ' '.join(type_and_comments[type_end:])

                # Clean up the designation
                designation = designation.replace(' ', '')

                # Look up P-object designation
                p_designation = p_objects.get(designation, '')

                objects.append({
                    'object': designation,
                    'type': obj_type.strip(),
                    'comments': comments.strip(),
                    'p-object': p_designation
                })

    # Write to CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['object', 'type', 'comments', 'p-object'])
        writer.writeheader()
        writer.writerows(objects)

def main():
    parser = argparse.ArgumentParser(description='Convert deep sky object text file to CSV.')
    parser.add_argument('input_file', help='Input text file to convert')
    parser.add_argument('-o', '--output', default='deep_sky_objects.csv',
                        help='Output CSV file (default: deep_sky_objects.csv)')

    args = parser.parse_args()

    try:
        process_text_to_csv(args.input_file, args.output)
        print(f"Successfully converted {args.input_file} to {args.output}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

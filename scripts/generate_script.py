import argparse
import random


def generate_commands(filename, num_lines, command_weights):
    all_commands = list(command_weights.keys())
    total_weight = sum(command_weights.values())
    command_percentages = {
        command: weight / total_weight for command, weight in command_weights.items()
    }

    cumulative_percentages = []
    cumulative_sum = 0
    for command in all_commands:
        cumulative_sum += command_percentages[command]
        cumulative_percentages.append(cumulative_sum)

    with open(filename, "w") as f:
        for _ in range(num_lines):
            rand_num = random.random()
            for idx, cumulative_percentage in enumerate(cumulative_percentages):
                if rand_num < cumulative_percentage:
                    command = all_commands[idx]
                    f.write(command + "\n")
                    break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a text file with commands.")
    parser.add_argument("filename", type=str, help="The name of the file to generate.")
    parser.add_argument("num_lines", type=int, help="The number of lines to generate.")
    args = parser.parse_args()

    command_weights = {
        "A": 20,
        "B": 15,
        "C": 15,
        "D": 15,
        "ENT": 10,
        "0": 4,
        "1": 4,
        "2": 4,
        "3": 4,
        "4": 4,
        "5": 4,
        "6": 4,
        "7": 4,
        "8": 4,
        "9": 4,
        "LNG_A": 10,
        "LNG_B": 3,
        "LNG_C": 3,
        "LNG_D": 3,
        "LNG_0": 3,
        "LNG_1": 1,
        "LNG_2": 1,
        "LNG_3": 1,
        "LNG_4": 1,
        "LNG_5": 1,
        "LNG_6": 1,
        "LNG_7": 1,
        "LNG_8": 1,
        "LNG_9": 1,
        "ALT_A": 7,
        "ALT_B": 3,
        "ALT_C": 3,
        "ALT_D": 3,
        "ALT_0": 1,
        "ALT_1": 1,
        "ALT_2": 1,
        "ALT_3": 1,
        "ALT_4": 1,
        "ALT_5": 1,
        "ALT_6": 1,
        "ALT_7": 1,
        "ALT_8": 1,
        "ALT_9": 1,
    }

    generate_commands(args.filename, args.num_lines, command_weights)

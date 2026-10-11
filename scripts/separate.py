import json
import os
from collections import defaultdict

# Input JSONL file
input_file = "/home/innocent/Implementations/My_Agentic_AI/my_agentic_ai/cvdp_benchmark/cvdp_v1.0.4_nonagentic_code_generation_no_commercial.jsonl"  # change this to your actual file path

# Output directory
output_dir = "data/catdata"
os.makedirs(output_dir, exist_ok=True)

# Dictionary to keep file handles and counts
category_files = {}
category_counts = defaultdict(int)

with open(input_file, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            print("Skipping invalid JSON line")
            continue

        # Extract category id (e.g., "cid003")
        categories = data.get("categories", [])

        # Find category that starts with "cid"
        cid_category = None
        for cat in categories:
            if cat.startswith("cid"):
                cid_category = cat
                break

        if cid_category is None:
            continue

        # Create file for this category if not already created
        if cid_category not in category_files:
            output_path = os.path.join(output_dir, f"{cid_category}.jsonl")
            category_files[cid_category] = open(output_path, "w", encoding="utf-8")

        # Write line to appropriate file
        category_files[cid_category].write(line + "\n")
        category_counts[cid_category] += 1

# Close all opened files
for f in category_files.values():
    f.close()

# Print counts
print("Line counts per category:")
for category, count in category_counts.items():
    print(f"{category}: {count}")
"""
Day 2 (corrected): Properly sample the Riiid dataset by random USER IDs,
not by row position.

Why: the raw train.csv is ordered by user (each user's full history is
contiguous). Taking the first N rows grabs a handful of users' complete
histories rather than a representative cross-section of the population.
This produces an extremely sparse item x user matrix that fails the
30-responses-per-item calibration threshold entirely.

This script:
  1. Reads ONLY the user_id column first (cheap, ~800MB for 100M+ rows)
     to build the universe of unique user IDs without loading the whole file.
  2. Randomly samples N_USERS from that universe.
  3. Scans the full file in chunks, keeping only rows belonging to the
     sampled users.
  4. Saves the result as a much smaller, properly-sampled CSV.

Run this against the full train.csv extracted from the Kaggle zip.
Expect this to take a few minutes depending on disk speed -- it has to
scan the full 5.5GB file once.
"""

import pandas as pd
import numpy as np

# ---- CONFIG: adjust this path to wherever you extracted train.csv ----
TRAIN_CSV_PATH = "train.csv"  # adjust if needed, e.g. r"C:\Users\moham\...\train.csv"
N_USERS = 3000                # how many unique users to sample
CHUNK_SIZE = 1_000_000        # rows per chunk when scanning the full file
OUTPUT_PATH = "riiid_sample_by_users.csv"
RANDOM_SEED = 42

np.random.seed(RANDOM_SEED)

print("Step 1: Reading user_id column only to find unique users...")
user_id_col = pd.read_csv(TRAIN_CSV_PATH, usecols=["user_id"])["user_id"]
unique_users = user_id_col.unique()
print(f"Total unique users in dataset: {len(unique_users):,}")

sampled_users = set(np.random.choice(unique_users, size=N_USERS, replace=False))
print(f"Randomly sampled {N_USERS:,} users.")
print()

print("Step 2: Scanning full file in chunks, keeping only sampled users...")
print("(This reads the whole 5.5GB file once -- may take a few minutes)")

chunks_kept = []
rows_seen = 0
for i, chunk in enumerate(pd.read_csv(TRAIN_CSV_PATH, chunksize=CHUNK_SIZE)):
    rows_seen += len(chunk)
    filtered = chunk[chunk["user_id"].isin(sampled_users)]
    if len(filtered) > 0:
        chunks_kept.append(filtered)
    if (i + 1) % 10 == 0:
        print(f"  ...scanned {rows_seen:,} rows so far, kept {sum(len(c) for c in chunks_kept):,} matching rows")

result = pd.concat(chunks_kept, ignore_index=True)
print()
print(f"Done. Final sample shape: {result.shape}")

result.to_csv(OUTPUT_PATH, index=False)
print(f"Saved to {OUTPUT_PATH}")
print()

# Quick sanity check before we even get to calibration
questions_only = result[result["content_type_id"] == 0]
responses_per_item = questions_only.groupby("content_id").size()
print("--- Sanity check ---")
print(f"Unique users: {result['user_id'].nunique():,}")
print(f"Unique questions: {questions_only['content_id'].nunique():,}")
print(f"Items with >= 30 responses: {(responses_per_item >= 30).sum():,}")
print(f"Median responses per item: {responses_per_item.median():.1f}")

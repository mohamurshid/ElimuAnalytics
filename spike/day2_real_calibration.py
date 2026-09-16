"""
Day 2: Real 2-PL MMLE calibration + EAP ability estimation on actual
Riiid response data (properly sampled by random user IDs).
"""

import pandas as pd
import numpy as np
import girth
import time

INPUT_PATH = "riiid_sample_by_users.csv"
MIN_RESPONSES_PER_ITEM = 30

print("Loading data...")
df = pd.read_csv(INPUT_PATH)
print(f"Raw shape: {df.shape}")

# Step 1: filter out lecture rows -- only real question responses matter
questions_only = df[df["content_type_id"] == 0].copy()
print(f"After filtering out lectures: {questions_only.shape}")

# Step 2: keep only items with enough responses to calibrate reliably
responses_per_item = questions_only.groupby("content_id").size()
valid_items = responses_per_item[responses_per_item >= MIN_RESPONSES_PER_ITEM].index
questions_only = questions_only[questions_only["content_id"].isin(valid_items)]
print(f"After filtering to items with >= {MIN_RESPONSES_PER_ITEM} responses: {questions_only.shape}")
print(f"Items remaining: {questions_only['content_id'].nunique():,}")
print(f"Users remaining: {questions_only['user_id'].nunique():,}")
print()

# Step 3: build the items x participants matrix that girth expects,
# filling missing (unanswered) cells with girth.INVALID_RESPONSE
print("Pivoting into items x participants matrix...")
pivot = questions_only.pivot_table(
    index="content_id",
    columns="user_id",
    values="answered_correctly",
    aggfunc="first"  # in case of duplicate attempts, just take the first
)
print(f"Matrix shape (items x participants): {pivot.shape}")

fill_value = girth.INVALID_RESPONSE
response_matrix = pivot.fillna(fill_value).astype(int).to_numpy()
n_missing = (response_matrix == fill_value).sum()
n_total = response_matrix.size
print(f"Sparsity: {n_missing:,} / {n_total:,} cells missing ({n_missing/n_total:.1%})")
print()

# Step 4: run the real calibration
print("Running 2-PL MMLE calibration on real data (this may take a moment)...")
start = time.time()
estimates = girth.twopl_mml(response_matrix)
elapsed = time.time() - start
print(f"Calibration completed in {elapsed:.1f} seconds")

discrimination = estimates["Discrimination"]
difficulty = estimates["Difficulty"]

print()
print("--- Item parameter summary ---")
print(f"Discrimination (a): min={discrimination.min():.2f}, max={discrimination.max():.2f}, "
      f"mean={discrimination.mean():.2f}, median={np.median(discrimination):.2f}")
print(f"Difficulty (b):     min={difficulty.min():.2f}, max={difficulty.max():.2f}, "
      f"mean={difficulty.mean():.2f}, median={np.median(difficulty):.2f}")
print()

# Sanity check: difficulty should correlate strongly (negatively) with raw
# proportion correct per item -- harder items = estimated as higher difficulty
# AND lower raw proportion correct. This is our real-data validity check
# since we don't have ground-truth parameters this time.
item_order = pivot.index.to_numpy()
raw_pct_correct = questions_only[questions_only["content_id"].isin(item_order)] \
    .groupby("content_id")["answered_correctly"].mean() \
    .reindex(item_order).to_numpy()

corr = np.corrcoef(difficulty, raw_pct_correct)[0, 1]
print(f"Correlation (estimated difficulty vs raw % correct): {corr:.3f}")
print("(Expect a STRONG NEGATIVE correlation -- harder items should have")
print(" both higher difficulty estimates AND lower raw correctness rates)")
print()

# Step 5: run EAP ability estimation
print("Running EAP ability estimation...")
start = time.time()
theta = girth.ability_eap(response_matrix, difficulty, discrimination)
elapsed = time.time() - start
print(f"Ability estimation completed in {elapsed:.1f} seconds")
print()
print("--- Ability (theta) summary ---")
print(f"min={theta.min():.2f}, max={theta.max():.2f}, mean={theta.mean():.2f}, "
      f"median={np.median(theta):.2f}, std={theta.std():.2f}")
print()

# Sanity check: theta should correlate strongly with each student's raw
# proportion correct across all their answered items
raw_pct_correct_by_user = questions_only.groupby("user_id")["answered_correctly"].mean()
user_order = pivot.columns.to_numpy()
raw_pct_by_user_ordered = raw_pct_correct_by_user.reindex(user_order).to_numpy()

theta_corr = np.corrcoef(theta, raw_pct_by_user_ordered)[0, 1]
print(f"Correlation (estimated theta vs raw % correct per student): {theta_corr:.3f}")
print("(Expect a STRONG POSITIVE correlation -- higher ability should")
print(" track with a higher raw proportion of correct answers)")
print()

print("--- VERDICT ---")
if corr < -0.5 and theta_corr > 0.7:
    print("PASS: the 2-PL MMLE + EAP pipeline behaves sensibly on real Riiid data.")
else:
    print("WARNING: correlations weaker than expected -- worth investigating further,")
    print("but this may still be usable; sparse real-world data is noisier than")
    print("the synthetic test from Day 1.")

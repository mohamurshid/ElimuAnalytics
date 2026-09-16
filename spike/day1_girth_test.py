"""
Day 1 spike test: confirm girth's 2-PL MMLE calibration + EAP ability estimation
actually works end-to-end on synthetic data, before touching the real Riiid dataset.

This does NOT use real data yet -- it generates a synthetic response matrix with
KNOWN true item parameters and known true student abilities, then checks whether
girth's calibration recovers parameters that are at least in the right ballpark.
"""

import numpy as np
import girth

np.random.seed(42)

N_ITEMS = 30
N_STUDENTS = 200

# Ground truth parameters we will try to recover
true_difficulty = np.random.uniform(-2, 2, N_ITEMS)
true_discrimination = np.random.uniform(0.5, 2.5, N_ITEMS)
true_theta = np.random.normal(0, 1, N_STUDENTS)

# Simulate responses using the 2-PL logistic model:
# P(correct) = 1 / (1 + exp(-a * (theta - b)))
def simulate_responses(theta, difficulty, discrimination):
    n_items = len(difficulty)
    n_students = len(theta)
    responses = np.zeros((n_items, n_students), dtype=int)
    for i in range(n_items):
        for j in range(n_students):
            p_correct = 1 / (1 + np.exp(-discrimination[i] * (theta[j] - difficulty[i])))
            responses[i, j] = int(np.random.random() < p_correct)
    return responses

print("Simulating response matrix: {} items x {} students...".format(N_ITEMS, N_STUDENTS))
response_matrix = simulate_responses(true_theta, true_difficulty, true_discrimination)
print("Response matrix shape:", response_matrix.shape)
print("Overall proportion correct: {:.2%}".format(response_matrix.mean()))
print()

print("Running 2-PL MMLE calibration (girth.twopl_mml)...")
estimates = girth.twopl_mml(response_matrix)
est_discrimination, est_difficulty = estimates['Discrimination'], estimates['Difficulty']

print()
print("--- Calibration sanity check ---")
print("True difficulty range:      [{:.2f}, {:.2f}]".format(true_difficulty.min(), true_difficulty.max()))
print("Estimated difficulty range: [{:.2f}, {:.2f}]".format(est_difficulty.min(), est_difficulty.max()))
print()
print("True discrimination range:      [{:.2f}, {:.2f}]".format(true_discrimination.min(), true_discrimination.max()))
print("Estimated discrimination range: [{:.2f}, {:.2f}]".format(est_discrimination.min(), est_discrimination.max()))
print()

# Correlation between true and estimated parameters -- should be reasonably high
# if calibration is working correctly (not a perfect match due to sampling noise,
# but should clearly track together)
diff_corr = np.corrcoef(true_difficulty, est_difficulty)[0, 1]
disc_corr = np.corrcoef(true_discrimination, est_discrimination)[0, 1]
print("Correlation (true vs estimated difficulty):     {:.3f}".format(diff_corr))
print("Correlation (true vs estimated discrimination): {:.3f}".format(disc_corr))
print()

print("Running EAP ability estimation (girth.ability_eap)...")
est_theta = girth.ability_eap(response_matrix, est_difficulty, est_discrimination)
theta_corr = np.corrcoef(true_theta, est_theta)[0, 1]
print("Correlation (true vs estimated theta): {:.3f}".format(theta_corr))
print()

print("--- VERDICT ---")
if diff_corr > 0.7 and disc_corr > 0.5 and theta_corr > 0.8:
    print("PASS: girth recovers parameters that track the ground truth well.")
    print("The 2-PL MMLE + EAP pipeline is working as expected.")
else:
    print("WARNING: correlations lower than expected -- investigate before proceeding.")

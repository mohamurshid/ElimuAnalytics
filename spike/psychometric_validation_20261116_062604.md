# Psychometric validation, 20261116_062604

Data: riiid_sample_by_users.csv (651,617 first attempts, 3,000 learners, 12,883 questions). Seed 169962.

## Model fit (target RMSEA below 0.06)

Dense block: 26 questions answered by all of 1,135 learners.

| Statistic | Value |
|---|---|
| M2 | 557.7 on 299 df (p = 7.41e-18) |
| RMSEA2 | **0.0276** (meets the 0.06 target) |
| Questions with discrimination below 0.3 | 2 of 26 |

Self-check, 50 data sets simulated from the fitted model: mean M2 305.4 against 299 df, mean RMSEA2 0.0045, p below 0.05 in 4.0% (about 5% expected if M2 is implemented correctly).

## Item fit (target infit and outfit 0.7 to 1.3)

900 calibrated questions: infit median 0.98, outfit median 0.97; both in range for 97.4% (infit 99.7%, outfit 97.7%); 170 with discrimination below 0.3.

## Criterion validity (target F1 0.75 or above)

Learners: 2,400 for calibration, 600 held out. Predictions: 20,781 later answers of held-out learners (56.5% correct).

| | F1, correct | F1, incorrect | Macro F1 | Accuracy | AUC |
|---|---|---|---|---|---|
| **2-PL ability model** | **0.721** | 0.592 | 0.657 | 66.9% | 0.723 |
| Always correct | 0.722 | 0.000 | 0.361 | 56.5% | 0.500 |
| Difficulty only | 0.714 | 0.564 | 0.639 | 65.5% | 0.700 |
| Learner's earlier proportion only | 0.672 | 0.439 | 0.556 | 58.6% | 0.594 |

Without the questions whose discrimination is below 0.3 (Section 3.2.3 excludes them; production does not yet), 17,355 predictions: F1 correct 0.724 (always correct 0.726), F1 incorrect 0.592, AUC 0.726.

Learner level (821 learner-batch pairs): ability from earlier answers against proportion correct on later answers, Pearson 0.395, Spearman 0.394.

Model precision / recall, correct: 0.688 / 0.758; incorrect: 0.638 / 0.553.

Batches: 1: 300 questions, 2,361 calibration learners, 447 held-out learners scored; 2: 300 questions, 1,834 calibration learners, 207 held-out learners scored; 3: 300 questions, 1,748 calibration learners, 167 held-out learners scored.

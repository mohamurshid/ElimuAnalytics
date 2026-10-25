# Question generation at scale - 20261025_073023

Model claude-haiku-5-5; 34 sub-strands (2 per grade/area pair, seed 169962); 5 questions asked per request. Production prompt, schema and checks. Every figure carries its n.

## Haiku, low effort

- requests: 34, failed 0 
- questions passing the checks: 92.9% (158/170)
- drop reasons (a question can have several): {'the question contains its own answer': 4, 'the curriculum excerpt is not in the curriculum text': 3, 'the correct option cannot carry a misconception': 4, 'it is a near-copy of another question': 1}
- cost: total $0.05738, mean $0.00169 per request (n=34)
- time: mean 15.0 s, 90th percentile 20.4 s
- key is the longest option: 38.0% (60/158) (chance ~25%)
- key position: {'A': 58, 'B': 53, 'C': 33, 'D': 14} (n=158)
- words per question: mean 13.6, max 42
- Kiswahili questions with English function words: 0.0% (0/26)

| learning area | passing the checks |
|---|---|
| Agriculture and Nutrition | 100.0% (30/30) |
| English | 100.0% (20/20) |
| Kiswahili | 86.7% (26/30) |
| Mathematics | 86.7% (26/30) |
| Science and Technology | 100.0% (30/30) |
| Social Studies | 86.7% (26/30) |

## Haiku, medium effort

- requests: 34, failed 0 
- questions passing the checks: 95.9% (163/170)
- drop reasons (a question can have several): {'the question contains its own answer': 3, 'the curriculum excerpt is not in the curriculum text': 2, 'the correct option cannot carry a misconception': 1, 'it is a near-copy of another question': 1}
- cost: total $0.08571, mean $0.00252 per request (n=34)
- time: mean 20.6 s, 90th percentile 25.8 s
- key is the longest option: 31.3% (51/163) (chance ~25%)
- key position: {'A': 25, 'B': 60, 'C': 52, 'D': 26} (n=163)
- words per question: mean 13.6, max 42
- Kiswahili questions with English function words: 0.0% (0/28)

| learning area | passing the checks |
|---|---|
| Agriculture and Nutrition | 93.3% (28/30) |
| English | 95.0% (19/20) |
| Kiswahili | 93.3% (28/30) |
| Mathematics | 93.3% (28/30) |
| Science and Technology | 100.0% (30/30) |
| Social Studies | 100.0% (30/30) |

## For a person to mark

- review_20261025_073023.csv: 40 saved questions, shuffled, setting hidden. Mark key_correct and misconceptions_ok.
- pairs_20261025_073023.csv: the most similar question pairs. Mark same_question.
- then: python spike\generation_at_scale.py --score 20261025_073023

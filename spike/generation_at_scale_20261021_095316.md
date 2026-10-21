# Question generation at scale - 20261021_095316

Model claude-haiku-5-5; 34 sub-strands (2 per grade/area pair, seed 169962); 5 questions asked per request. Production prompt, schema and checks. Every figure carries its n.

## Haiku, low effort

- requests: 34, failed 0 
- questions passing the checks: 84.1% (143/170)
- drop reasons (a question can have several): {'the correct option cannot carry a misconception': 21, 'two options are the same': 1, 'the curriculum excerpt is not in the curriculum text': 1, 'the question contains its own answer': 3, 'it is a near-copy of another question': 2}
- cost: total $0.05893, mean $0.00173 per request (n=34)
- time: mean 15.2 s, 90th percentile 20.3 s
- key is the longest option: 31.5% (45/143) (chance ~25%)
- key position: {'A': 54, 'B': 43, 'C': 31, 'D': 15} (n=143)
- words per question: mean 14.2, max 34
- Kiswahili questions with English function words: 0.0% (0/26)

| learning area | passing the checks |
|---|---|
| Agriculture and Nutrition | 80.0% (24/30) |
| English | 75.0% (15/20) |
| Kiswahili | 86.7% (26/30) |
| Mathematics | 76.7% (23/30) |
| Science and Technology | 83.3% (25/30) |
| Social Studies | 100.0% (30/30) |

## Haiku, medium effort

- requests: 34, failed 1 ['cut off']
- questions passing the checks: 91.5% (151/165)
- drop reasons (a question can have several): {'the curriculum excerpt is not in the curriculum text': 1, 'the correct option cannot carry a misconception': 10, 'it is a near-copy of another question': 2, 'the question contains its own answer': 1}
- cost: total $0.08734, mean $0.00257 per request (n=34)
- time: mean 21.0 s, 90th percentile 26.9 s
- key is the longest option: 33.8% (51/151) (chance ~25%)
- key position: {'A': 30, 'B': 46, 'C': 47, 'D': 28} (n=151)
- words per question: mean 14.5, max 41
- Kiswahili questions with English function words: 0.0% (0/17)

| learning area | passing the checks |
|---|---|
| Agriculture and Nutrition | 100.0% (30/30) |
| English | 100.0% (20/20) |
| Kiswahili | 68.0% (17/25) |
| Mathematics | 96.7% (29/30) |
| Science and Technology | 83.3% (25/30) |
| Social Studies | 100.0% (30/30) |

## For a person to mark

- review_20261021_095316.csv: 40 saved questions, shuffled, setting hidden. Mark key_correct and misconceptions_ok.
- pairs_20261021_095316.csv: the most similar question pairs. Mark same_question.
- then: python spike\generation_at_scale.py --score 20261021_095316

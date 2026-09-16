"""
Day 5: RAG spike using REAL KICD curriculum content.

Embeds the 8 curriculum chunks extracted from the official KICD Grade 5
Science & Technology Curriculum Design (Revised 2024), retrieves the most
relevant ones for a flagged learner, builds the RAG prompt, and calls the
Claude API to generate a diagnostic report.

Requires:
  pip install sentence-transformers anthropic numpy
  ANTHROPIC_API_KEY set as an environment variable

Run:
  python day5_rag_spike_real.py
"""

import os
import numpy as np
from sentence_transformers import SentenceTransformer
from anthropic import Anthropic

from kicd_curriculum_chunks import CURRICULUM_CHUNKS, RUBRIC_LEVELS

# Use Haiku during development iteration to keep costs minimal.
# Switch to "claude-sonnet-4-5" for final demo / evaluation runs.
MODEL = "claude-haiku-4-5-20251001"

# A flagged learner, as the GapDetectionModule would produce.
# theta = -1.8 maps to "Below expectation" on the KICD four-level rubric.
FAKE_LEARNER = {
    "name": "Chebet K.",
    "grade": "Grade 5",
    "strand": "3.0 Force and Energy",
    "sub_strand": "3.3 Heat Transfer",
    "theta": -1.8,
    "ability_tier": "Below expectation",
    "consecutive_flags": 2,
}


def embed_chunks(chunks, model):
    return model.encode([c["text"] for c in chunks])


def retrieve(query, chunks, chunk_embeddings, model, top_k=2):
    q = model.encode([query])[0]
    sims = np.dot(chunk_embeddings, q) / (
        np.linalg.norm(chunk_embeddings, axis=1) * np.linalg.norm(q)
    )
    top = np.argsort(sims)[::-1][:top_k]
    return [(chunks[i], float(sims[i])) for i in top]


def build_prompt(learner, retrieved):
    context = "\n\n".join(c["text"] for c, _ in retrieved)
    tiers = ", ".join(RUBRIC_LEVELS)
    return f"""You are an educational advisor writing a diagnostic report for a Kenyan primary school teacher.

CURRICULUM CONTEXT (retrieved from the official KICD Grade 5 curriculum design):
{context}

LEARNER PERFORMANCE:
- Learner: {learner['name']}, {learner['grade']}
- Strand: {learner['strand']}
- Sub-strand: {learner['sub_strand']}
- Estimated ability (IRT theta): {learner['theta']}
- KICD rubric level: {learner['ability_tier']}
- Flagged as at-risk for {learner['consecutive_flags']} consecutive assessments

The KICD rubric levels are: {tiers}

Write a 3-paragraph report addressed to the class teacher:
Paragraph 1: Summarise the learner's current standing against the KICD rubric level.
Paragraph 2: Identify the specific gap, referencing the Specific Learning Outcomes
             from the curriculum context above.
Paragraph 3: Recommend ONE concrete classroom activity, drawn directly from the
             Suggested Learning Experiences in the curriculum context.

Use clear, professional English. Maximum 200 words. Do not invent curriculum
content that is not present in the context above."""


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY not set.\n"
            'Windows:  setx ANTHROPIC_API_KEY "sk-ant-..."  (then reopen terminal)'
        )

    print("Loading embedding model (first run downloads ~90MB)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print(f"Embedding {len(CURRICULUM_CHUNKS)} real KICD curriculum chunks...")
    embeddings = embed_chunks(CURRICULUM_CHUNKS, model)

    query = f"{FAKE_LEARNER['strand']} {FAKE_LEARNER['sub_strand']}"
    print(f"\nRetrieval query: '{query}'\n")

    retrieved = retrieve(query, CURRICULUM_CHUNKS, embeddings, model, top_k=2)

    print("--- RETRIEVAL CHECK ---")
    print("(The Heat Transfer chunk should rank #1. If an unrelated strand")
    print(" like 'Classification of plants' ranks top, retrieval is broken.)\n")
    for rank, (chunk, score) in enumerate(retrieved, 1):
        print(f"  #{rank}  [{score:.3f}]  {chunk['sub_strand']}")

    # Show full similarity ranking for transparency
    all_scores = []
    q_emb = model.encode([query])[0]
    sims = np.dot(embeddings, q_emb) / (
        np.linalg.norm(embeddings, axis=1) * np.linalg.norm(q_emb)
    )
    print("\n  Full ranking:")
    for i in np.argsort(sims)[::-1]:
        print(f"    {sims[i]:.3f}  {CURRICULUM_CHUNKS[i]['sub_strand']}")

    prompt = build_prompt(FAKE_LEARNER, retrieved)

    print(f"\nCalling Claude API (model: {MODEL})...")
    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )

    print("\n" + "=" * 70)
    print("GENERATED DIAGNOSTIC REPORT")
    print("=" * 70)
    print(resp.content[0].text)
    print("=" * 70)

    usage = resp.usage
    print(f"\nToken usage: {usage.input_tokens} in / {usage.output_tokens} out")
    cost = (usage.input_tokens / 1e6) * 1.00 + (usage.output_tokens / 1e6) * 5.00
    print(f"Approx cost this call: ${cost:.6f}")


if __name__ == "__main__":
    main()

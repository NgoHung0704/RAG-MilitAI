"""
RAG chain: retriever + LLM prompt + answer with citations.
"""

from __future__ import annotations

from openai import OpenAI

from app.rag.retriever import retrieve


_SYSTEM_PROMPT = """
You are a historian specialising in French Ancien Régime military records (17th–18th century).
You answer questions about soldiers based ONLY on the archival records provided as context.
If the answer cannot be found in the context, say so clearly — do not invent information.
When you cite a soldier, mention their name and the source record if available.
Reply in the same language the user asked the question in.
""".strip()


def build_rag_prompt(question: str, chunks: list[dict]) -> str:
    """Format retrieved chunks into a numbered context block for the LLM."""
    context_blocks: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk["metadata"]
        header = f"[Record {i}]"
        ark = meta.get("ark_url")
        if ark:
            header += f"  (source: {ark})"
        context_blocks.append(f"{header}\n{chunk['text']}")

    context = "\n\n".join(context_blocks)
    return (
        f"## Archival context\n\n{context}\n\n"
        f"## Question\n\n{question}"
    )


def answer_with_rag(
    question: str,
    client: OpenAI,
    persist_dir: str,
    model_name: str,
    k: int,
) -> dict:
    """
    Full RAG pipeline: retrieve → build prompt → generate answer.

    Returns:
        {
          "answer":  str,
          "sources": list[dict]   # metadata dicts for each retrieved chunk
        }
    """
    chunks = retrieve(question, k, persist_dir, model_name)
    prompt = build_rag_prompt(question, chunks)

    resp = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=1024,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
    )

    return {
        "answer": resp.choices[0].message.content,
        "sources": [c["metadata"] for c in chunks],
    }

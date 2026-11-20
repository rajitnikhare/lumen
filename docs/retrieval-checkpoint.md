# Lumen: Retrieval Design and Working Agent Update

## 1. Why retrieval is required

Lumen is a local-first personal AI assistant that helps users understand their documents, consult saved notes, draft messages, and organize small tasks. Retrieval is required when an answer depends on personal information that the model does not already have. For example, answering “What time is my train?” requires evidence from an authorized ticket or itinerary rather than a guess from the model's training.

Retrieval is not necessary for every workflow. General explanations, drafting from explicitly supplied text, and saving a note or reminder can operate without searching the library. The design therefore uses retrieval to ground document-based questions rather than treating RAG as a requirement for every interaction. Retrieved information augments the prompt; it does not retrain the model or give the assistant permission to execute actions.

## 2. External data source and semantic integration

The external knowledge source is the user’s explicitly imported PDF, Word, TXT, or Markdown documents, supplemented by authorized saved notes. “External” means external to the language model’s training and existing context, not necessarily an internet service. This choice matches Lumen’s purpose: answering questions about personal material while keeping that material on the user’s computer.

The working update adds optional semantic retrieval through Ollama’s local embedding API, using `nomic-embed-text` as the recommended embedding model. Users configure it separately from the response-generation model in Settings. Only documents and notes with AI access enabled become retrieval candidates. Lumen embeds the question and candidate passages, compares their vectors using cosine similarity, and passes selected excerpts to the local chat model.

Each excerpt includes a title, location, and source label such as `[S1]`; the title is separate from the citation ID. The model is instructed to cite supplied evidence for personal facts and acknowledge missing information. Source information makes answers inspectable, not automatically trustworthy. Chat also displays the retrieval method and number of excerpts supplied. Keyword retrieval remains the default until semantic retrieval is enabled. Embedding failures are reported explicitly, without silently switching methods.

## 3. Key retrieval design choices

Documents are segmented into chunks of up to 2,000 UTF-8 bytes, with approximately 150 bytes of overlap. The overlap reduces the chance of losing related information at a chunk boundary, while bounded chunks help manage local-model context limits. PDF chunks retain page locations, and each passage is embedded alongside its document title to provide additional context.

Semantic retrieval supplies at most two excerpts per question, accepting only passages with a cosine similarity of at least 0.5. This keeps the prompt focused but can omit evidence needed for complex, cross-document questions. The threshold is a heuristic, not a calibrated confidence score. Keyword retrieval instead ranks word overlap and does not use a cosine threshold. Explicitly attached files restrict the search to those files; keyword attachment mode retains its opening-excerpts fallback when no words match, while semantic mode does not.

Embeddings are recomputed in batches of up to 16 passages per question and are not persisted in a separate vector index. Document records remain encrypted in the vault. This implementation prioritizes simplicity and privacy for a small prototype library, accepting additional latency as the collection grows.

## 4. Demonstrated influence on the response

The following is a historical demonstration, not a newly measured quality benchmark. Model wording and behavior can vary. Use `scripts/demo_retrieval.py` with explicitly installed local models to repeat the synthetic comparison in a temporary vault.

For example, I added a document to Lumen that said, “Terminate unused memberships. Estimated monthly savings: USD 47.” Then I asked, “How can I lower my bills?”

Without semantic retrieval, Lumen gave general budgeting advice because it did not find the document through keyword matching.

With semantic retrieval enabled, Lumen recognized that “lower my bills” was related to “monthly savings.” It found the document, suggested canceling unused memberships, included the estimated monthly savings of $47, and cited the source.

When I removed Lumen’s permission to use the document, it returned to general advice and no longer included the $47 figure. This shows that the retrieved document supplied the specific information in the answer—it was not simply a guess from the model.

## 5. Failure mode and risk management

A key failure mode is retrieving a semantically similar passage that does not actually support the requested conclusion. A passage about someone else’s expenses, for example, could resemble the question while being inappropriate evidence for the user’s own situation.

Lumen reduces this risk through a minimum similarity threshold, a small result set, instructions to acknowledge missing evidence, and source excerpts that users can inspect. It rejects invented citation labels, but validating a label does not prove that the cited text supports a claim or guarantee that the model will decline to answer when evidence is missing. Broader evaluation with paraphrases, misleading passages, and unanswerable questions is still needed.

Separately, authorization and revision checks between embedding batches and before and after generation prevent changed or revoked records from being silently reused. These safeguards help manage risk without claiming that RAG guarantees factual correctness.

# Tree of Thought Assessment

Tree of Thought (ToT) reasoning is not necessary for my capstone project, **Lumen**, a local-first personal AI assistant. Its current features—document Q&A, summarization, email drafting, notes, reminders, and user-approved research—primarily require accurate retrieval, grounded responses, and explicit user control rather than exploration of multiple planning paths.

Adding ToT would likely hinder the current design by increasing local model calls, response times, and implementation complexity without a clear improvement in quality. Better retrieval and evidence validation would provide more value. ToT could become appropriate if Lumen later supports complex planning, such as comparing multi-city itineraries under budget and scheduling constraints, but it is not justified for the existing feature set.

## Why ToT Is Not Appropriate

I considered ToT's ability to generate, evaluate, and backtrack across alternative solution paths. It is most useful when early choices affect later possibilities, several plausible paths exist, and there is a meaningful way to judge which path is better. A tightly constrained itinerary is an example: selecting one city order changes transport options, costs, and the time available for activities. Lumen's existing features generally do not have this branching structure, so I intentionally chose not to add a tree-search layer.

### The Main Challenge Is Evidence, Not Searching for a Plan

For document Q&A, Lumen needs to find relevant authorized passages and answer within what they support. If a user asks for a deadline in an uploaded document, retrieving the correct passage matters more than generating several possible explanations. A tree of candidate answers cannot recover evidence that was never retrieved. Some questions may require comparing passages or making several logical steps, but multi-step reasoning alone does not require ToT.

Similarly, summarization needs adequate source coverage and faithful compression. Lumen already processes large documents in chunks and combines the partial summaries. Although this involves multiple model calls and a hierarchical structure, it is not ToT: those calls cover portions of a document rather than explore competing solution paths. Branching over alternative summaries would not, by itself, guarantee that important facts are preserved.

### Existing Actions Have Explicit Inputs and Outcomes

Saving a note, setting a reminder, or marking a reminder complete is an application operation, not an open-ended reasoning problem. Once the user provides and confirms the required information, deterministic code should perform the operation and report its actual result. If information is missing, such as a reminder's due date, explicit user input is more reliable than exploring guessed alternatives. ToT would add little value to these operations and must not replace their confirmation or permission checks.

Email drafting and contextual suggestions do allow multiple reasonable answers, but that does not automatically justify tree search. A useful initial draft followed by user-directed revision is sufficient for the current workflow. The user's preferences determine whether a draft is appropriate; a model evaluating its own branches may not know those preferences. Generating a few alternatives on request is also possible without implementing recursive expansion and backtracking.

### More Reasoning Does Not Supply Stronger Verification

Lumen's research feature compares user-approved search-result snippets, not independently verified full articles. A model could explore several interpretations of those snippets, but doing so would not provide additional evidence. If the same model generates and evaluates candidates, it may favor a convincing but unsupported answer. ToT is therefore not a substitute for better sources, citation inspection, or acknowledging uncertainty. Lumen's source-ID checks confirm that a citation refers to supplied material, not that the material supports every claim.

### Local Execution Makes the Added Cost Significant

Lumen runs inference locally through Ollama. A ToT workflow would typically require extra generation and evaluation calls, with cost increasing as more branches and search levels are explored. On a laptop, this could increase response times and resource use. It would also introduce decisions about branch limits, stopping conditions, candidate scoring, and failure handling. Those costs could be justified by a demonstrated quality improvement, but the current feature set does not establish that need.

### The Design Prioritizes Bounded Assistance and User Control

Lumen is a user-directed assistant, not an autonomous action planner. Its current workflows keep requests scoped and require explicit approval for sensitive operations and external research. ToT can be implemented within those boundaries and is not inherently incompatible with privacy. However, introducing it would require carrying the same authorization and revision checks through every additional stage without a clear current benefit.

My decision is therefore based on fit, not on the assumption that ToT is ineffective. For the existing capstone scope, better retrieval, faithful summaries, clear uncertainty, and user feedback target the actual failure modes more directly. I would reconsider ToT for a future feature with genuinely interdependent choices, measurable constraints, and evidence that a simpler planner cannot produce satisfactory results.

## Best-Fit Reasoning Approach

Lumen is best served by a **bounded, sequential, evidence-grounded workflow**, using retrieval-augmented generation (RAG) for document and note Q&A. It retrieves authorized excerpts, supplies them with the user's request to a local model, and checks that any cited source IDs belong to the supplied sources. Full-document summaries use chunk-and-combine processing, while record changes remain deterministic and user-controlled. This is not a ToT search or an implementation that requires exposed chain-of-thought reasoning.

## Why This Approach Better Supports Lumen's Goal

This approach supports Lumen's goal of private, useful assistance by keeping model work focused, limiting local computation, and preserving permission boundaries and user control. Retrieved sources make answers easier to inspect, although valid citations alone do not guarantee factual accuracy. User clarification and revision provide a direct way to improve results without evaluating a tree of speculative alternatives.

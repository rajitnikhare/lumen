# Lumen: Proposed Multi-Agent Architecture

## 1. System purpose and need for multiple agents

My capstone project, **Lumen**, is a local-first assistant for personal documents, notes, message drafts, reminders, and approved public research. It turns private information into evidence-grounded assistance without surrendering user control.

A complex request is: “Compare the cancellation terms in my authorized membership documents with public guidance, then draft a cancellation email.” This requires evidence collection, comparison, and writing. External searches still require approval of the exact query.

One agent could attempt everything, but separating evidence collection, writing, and review makes failures easier to diagnose. Multi-agent processing is selective: simple questions use one response agent, while saving notes and reminders remains deterministic application behavior.

**This is a proposed extension:** the current Lumen application uses bounded local-model workflows, not this coordinated multi-agent system.

## 2. Agent count, roles, and responsibilities

The system would contain **three specialized agents**, managed by a deterministic application controller. The controller enforces rules and routes work; it is not a fourth AI agent.

| Agent | Responsibilities | Boundaries |
|---|---|---|
| **Evidence Agent** | Identify relevant passages through controller-mediated retrieval of authorized documents and notes; organize approved search snippets; preserve source locations; flag gaps and conflicts. | Cannot authorize records, initiate unapproved internet requests, or modify user data. |
| **Response Agent** | Turn the evidence package into an answer, comparison, summary, or draft. Cite supporting sources and distinguish evidence from general knowledge and uncertainty. | Cannot send messages, change records, or expand its access. |
| **Review Agent** | Compare the candidate response with supplied evidence. Flag unsupported claims, inconsistent dates or amounts, missing qualifications, and false claims of completed actions. | Read-only access to the request, permitted evidence, and candidate response; no independent browsing or vault access. |

Three roles balance complexity and separation of concerns. Two agents would combine evidence gathering with writing, or writing with review. A fourth planner or citation specialist would add handoffs without a distinct need: bounded routing and citation-ID checks can remain application code.

This reflects **diminishing returns**: more agents need measurable benefits beyond their coordination cost. The roles may share one local Ollama model with separate contexts, limiting memory requirements without claiming independent judgment.

## 3. Coordination strategy

Lumen would use a **hybrid workflow: centralized routing, a sequential core, and one bounded feedback loop**.

```text
User → Controller → Evidence → Response → Review → Final validation → User
                                  ↑          │
                                  └──────────┘
                                One revision maximum
```

The sequence follows dependencies: writing needs evidence, and review needs a candidate response. Correctable issues trigger targeted feedback, one revision, and a final review. Persistent problems produce a limitation or clarification request—not an endless loop or an apparent success.

The controller handles timeouts, permissions, and simple-task bypasses. A broad graph-based network is unnecessary because dependencies are clear. Independent evidence operations could later run concurrently; local model execution would initially remain serialized to manage laptop resources.

## 4. Communication and information exchange

Communication would use **one-way structured handoffs**, with limited two-way validation through the controller. Messages contain the user goal, task ID, permitted source IDs and revisions, excerpts and locations, candidate response, and review findings. Each agent receives only what its role needs.

Additional evidence requests return to the controller; they never grant permissions or automatically trigger searches. Source content remains untrusted data, not instructions. Open-ended brainstorming is excluded because these tasks need faithful evidence handling rather than exploration of competing plans.

## 5. Trade-offs and design rationale

- **Reliability versus latency:** dedicated review and bounded feedback may catch unsupported claims, but require additional inference. Review is a safeguard, not proof of correctness; agents sharing a model may repeat the same mistakes.
- **Specialization versus complexity:** role separation improves accountability and failure diagnosis, but adds message contracts, prompts, and integration tests. Three agents keep this manageable.
- **Central control versus flexibility:** one controller provides consistent authorization and predictable routing, but becomes a critical component that requires careful testing.
- **Sequential execution versus throughput:** dependency-aware ordering simplifies coordination and limits memory pressure, but is slower than a single call. Selective routing avoids this overhead for simple tasks.
- **Bounded context versus coverage:** concise evidence packages reduce processing cost but may omit relevant material. Agents must report gaps rather than assume that selected excerpts represent an entire document.

These decisions apply the concepts of specialization, separation of concerns, dependency-based coordination, structured communication, and bounded iteration. Permissions and record revisions would be checked between stages and before saving; locking the vault or revoking a source would invalidate affected results. Deterministic checks—not agent agreement—enforce these boundaries.

## 6. Effective and scalable problem solving

The architecture scales by decomposing work into stable responsibilities, not by continually adding agents. Evidence can be processed in bounded batches, while summaries retain Lumen's chunk-and-combine approach for long documents. Explicit handoffs allow retrieval, generation, or review to improve independently. The controller can apply workload limits and reject overlapping model work rather than overload the device.

This does not remove existing bottlenecks: recomputing embeddings per question becomes slower as the library grows, and review adds model calls. I would compare the proposal against the current single-agent baseline using synthetic tasks, measuring correctness, unsupported claims, citation support, permission compliance, latency, and resource consumption.

Success means better evidence-grounded assistance at an acceptable local cost—not a larger agent count or greater autonomy.

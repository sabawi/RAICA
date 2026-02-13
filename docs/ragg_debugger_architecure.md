This is a refined and expanded version of your architecture document. It maintains the "no fluff" engineering mandate while filling in the implementation gaps required to move from "High Level Design" (HLD) to "Low Level Design" (LLD).

I have added specific technical strategies for **Tree-sitter integration**, **incremental graph maintenance**, **vector-based semantic search**, and **LSP (Language Server Protocol)** compatibility.

---

# Architecture Specification v2.0

**Language-Agnostic Code Intelligence, Refactoring & LLM-Assisted Debugging Engine**

## 1. Purpose & Scope (Refined)

**Purpose**
Build a high-performance, local-first static analysis engine that converts polyglot source code into a queryable **Semantic Knowledge Graph**. This graph serves as the ground truth for:

* **Deterministic Tooling:** Navigation, safe refactoring, and static analysis (linting/dead code).
* **Probabilistic Tooling:** RAG-backed context generation for LLMs to minimize hallucination during debugging and code generation tasks.

**Non-Goals (Explicit)**

* **Runtime Emulation:** We do not execute code. We model control flow, not data values (except for constant propagation).
* **Compiler Replacement:** We do not generate binary executables.
* **Universal Grammar:** We do not attempt to map 100% of language syntax to UIR, only semantically relevant structures (80/20 rule).

---

## 2. Architectural Principles

1. **The Graph is the API:** All features (LSP, Refactoring, Chat) are just queries over the Semantic Graph.
2. **Lazy & Incremental:** Parse only changed files; re-analyze only affected sub-graphs.
3. **Graceful Degradation:** If an adapter fails to parse a function, the rest of the file must still be indexed.
4. **Strict Layering:** Lower layers (Adapters) never depend on higher layers (Graph/Analysis).
5. **Token Budget Awareness:** LLM context context building is an optimization problem (Max Information / Min Tokens).

---

## 3. High-Level System Architecture

```mermaid
graph TD
    src[Source Files] -->|Watch| fs[File System Watcher]
    fs -->|Delta| adp[Adapter Layer]
    
    subgraph "Ingestion Pipeline"
        adp -->|Tree-sitter| cst[Concrete Syntax Tree]
        cst -->|Query| uir[Unified IR Nodes]
    end
    
    uir -->|Upsert| sg[Semantic Graph Core]
    
    subgraph "Storage Layer"
        sg -->|Nodes/Edges| kv[KV Store (RocksDB/LMDB)]
        sg -->|Embeddings| vec[Vector Store (Chroma/Faiss)]
        sg -->|Relations| sql[Relational Index (SQLite)]
    end
    
    subgraph "Presentation Layer"
        lsp[LSP Server] -->|JSON-RPC| ide[IDE Client]
        llm[LLM Context Builder] -->|Prompt| model[Local/Remote LLM]
    end
    
    sg -->|Query| lsp
    sg -->|Slice| llm

```

---

## 4. Language Adapter Layer (Expanded)

**Implementation Strategy: Tree-sitter Query Engine**
Instead of writing custom walkers for every language, we utilize **Tree-sitter** and **SCM (Scheme-like)** capture queries to map syntax to UIR.

**Adapter Interface**

```python
class LanguageAdapter(Protocol):
    """
    Stateless transformer. Converts file content to UIR stream.
    """
    def parse(self, content: bytes, file_path: str) -> Tree: ...
    
    def extract(self, tree: Tree, source: bytes) -> Iterator[UIRNode | UIREdge]: ...
    
    def get_query_files(self) -> dict[str, str]:
        """Returns paths to 'tags.scm', 'locals.scm' for Tree-sitter."""

```

**Tree-sitter Query Example (Python)**
Mapping a function definition to UIR:

```scheme
(function_definition
  name: (identifier) @name
  parameters: (parameters) @params
  body: (block) @body
) @function_scope

```

---

## 5. Unified Intermediate Representation (UIR)

**Schema Definition (Protobuf/DataClass style)**
The UIR is the "Rosetta Stone" that normalizes C++ `structs`, Python `classes`, and Go `structs` into a single entity type.

**UIRNode**

```python
@dataclass(slots=True)
class UIRNode:
    id: str                 # Content-addressable hash (SHA256 of signature)
    file_path: str
    kind: NodeKind          # ENUM: FUNCTION, CLASS, VAR, INTERFACE...
    name: str               # "calculate_velocity"
    type_sig: str | None    # "float -> float" (normalized)
    range: TextRange        # start_line, start_col, end_line, end_col
    docstring: str | None   # Extracted for LLM context
    is_exported: bool       # For visibility analysis
    metadata: dict          # Language-specific extras (e.g., decorators)

```

**UIREdge**

```python
@dataclass(slots=True)
class UIREdge:
    src_id: str
    dst_id: str
    kind: EdgeKind
    weight: float = 1.0     # Relevance weight for ranking

```

---

## 6. Semantic Graph Layer (The Core)

**Data Structure: Property Multi-DiGraph**
We require a graph structure supporting multiple edge types between nodes (e.g., A *calls* B, and A *imports* B).

**Graph Partitioning**

1. **Static Call Graph (SCG):** Who calls whom.
2. **Import Graph:** File/Module dependencies.
3. **Data Dependency Graph (DDG):** Variable usage (Def-Use chains).
4. **Inheritance Graph:** Class hierarchy.

**Storage Strategy (Engineering Choice)**

* **Nodes/Edges:** `NetworkX` (Python prototype)  `Rust/Petgraph` (Production).
* **Persistence:** `SQLite` is sufficient for up to ~500k LOC. Beyond that, use an embedded graph store like `KùzuDB` or `DuckDB` with recursive CTEs.

---

## 7. Analysis Engine

**Static Analysis Passes**

1. **Symbol Resolution (Linking):**
* *Input:* Unresolved `CALL` edges.
* *Logic:* Scoping rules traversal (Lexical  Module  Global).
* *Output:* Resolved `DEFINES` edges connecting usage to definition.


2. **Taint Analysis (Security/Debugging):**
* *Input:* A source node (e.g., `user_input`).
* *Logic:* Forward traversal along `DATA_FLOW` edges.
* *Output:* Set of potentially impacted nodes (Impact Analysis).


3. **Cyclomatic Complexity Calculation:**
* Used to flag "complex code" for the LLM to prioritize when asked to "refactor for readability."



---

## 8. Index & Storage Layer

**Hybrid Storage Model**

| Data Type | Storage Engine | Purpose |
| --- | --- | --- |
| **Relational Metadata** | **SQLite** | Fast lookups by filename, symbol name, line number. |
| **Graph Topology** | **Adjacency List (In-Mem)** | Millisecond traversal for call hierarchies. |
| **Semantic Embeddings** | **ChromaDB / Faiss** | Vector search ("Find code that parses CSVs"). |
| **Source Blobs** | **Content-Addressed File Store** | Version control agnostic file retrieval. |

---

## 9. Refactoring Engine

**Safety Guarantee Protocol**
Before applying a refactor (e.g., Rename `x` to `y`), the engine must prove:

1. **Resolution Invariance:** `y` does not already exist in the scopes where `x` is referenced (Shadowing check).
2. **Syntax Validity:** The change does not violate language grammar.

**Transaction Flow**

```text
1. User requests: Rename(SymbolID="A", NewName="B")
2. Engine Queries: Find all references to "A" (incoming 'USES' edges)
3. Engine Checks: Is "B" defined in the scope of any reference?
    -> YES: Abort (Collision detected)
    -> NO:  Generate Diff Patch
4. Apply Patch -> Re-parse affected files -> Update Graph

```

---

## 10. Incremental Processing (The "Dirty" Logic)

**State Tracking**
Maintain a `file_hash_map`. On startup:

1. Scan files. Compute `current_hash`.
2. Compare with `stored_hash`.
3. Identify `changed_files`, `added_files`, `deleted_files`.

**Cascade Updates**

* **File Changed:**
1. Remove all nodes/edges where `file_path == changed_file`.
2. Re-parse file  Generate new UIR.
3. **Re-Link Phase:** Re-run Symbol Resolution only for nodes that reference *or* are referenced by the changed symbols.



---

## 11. LLM Integration (RAG for Code)

**Context Builder Pipeline**

The goal is to fit the *perfect* context into the context window (e.g., 8k/32k tokens).

**Algorithm: The "Semantic Slice"**
Given a user query focused on function `target_func`:

1. **Core:** Include code of `target_func`.
2. **1-Hop Defs:** Include signatures/docstrings of all functions `target_func` calls.
3. **1-Hop Refs:** Include snippet of 3-5 distinct usages of `target_func` (to show how it's used).
4. **Types:** Include definitions of custom types/classes used in signatures.
5. **Vector Search (Optional):** Add 2-3 snippets of "conceptually similar" code from the codebase.

**Prompt Assembler (XML-Structured)**

```xml
<context>
    <file path="src/main.py">
        <definition line="10-50"> ... code ... </definition>
    </file>
    <dependencies>
        <interface name="User" line="5">class User: ...</interface>
    </dependencies>
    <usage_examples>
        <callsite line="99">process_user(u)</callsite>
    </usage_examples>
</context>

```

---

## 12. Interface & Deployment

**LSP Server (Primary Interface)**
Implement the **Language Server Protocol**:

* `textDocument/definition`: Query Graph for `DEFINES` edge.
* `textDocument/references`: Query Graph for incoming `USES` edges.
* `textDocument/rename`: Trigger Refactoring Engine.
* `textDocument/hover`: Show inferred type + docstring + LLM summary.

**CLI Tool**

* `codemap index .`: Build the database.
* `codemap query "SELECT name FROM functions WHERE complexity > 10"`: SQL-over-code.
* `codemap explain <symbol_name>`: Pipe Semantic Slice to LLM.

---

## 13. Implementation Roadmap (Refined)

**Phase 1: The Skeleton (Weeks 1-4)**

* Setup Tree-sitter for Python.
* Implement `UIRNode` and `UIREdge` data structures.
* Build the `SQLite` indexer for symbol definitions.
* **Deliverable:** A CLI that lists all functions in a Python project.

**Phase 2: The Graph (Weeks 5-8)**

* Implement Reference resolution (basic scoping).
* Build the Call Graph construction logic.
* **Deliverable:** "Find Usages" working reliably.

**Phase 3: LLM & Refactor (Weeks 9-12)**

* Implement `ContextBuilder` (Slicing logic).
* Integrate local LLM API (e.g., Ollama/Llama.cpp).
* Implement "Rename" refactoring.
* **Deliverable:** An LSP server that can explain code and rename variables.

Next steps:
* High Level Design (HLD)

* Low Level Design (LLD)



# RAGG Debugger - High-Level Design Document (HLD)

**Version:** 1.0  
**Document Type:** High-Level Design (HLD)  
**Project:** Language-Agnostic Code Intelligence, Refactoring & LLM-Assisted Debugging Engine  
**Date:** 2026-01-18  
**Authors:** Senior Engineering Team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Vision & Goals](#2-system-vision--goals)
3. [Architectural Overview](#3-architectural-overview)
4. [Component Architecture](#4-component-architecture)
5. [Data Architecture](#5-data-architecture)
6. [Integration Architecture](#6-integration-architecture)
7. [Technology Stack](#7-technology-stack)
8. [Quality Attributes](#8-quality-attributes)
9. [Security Considerations](#9-security-considerations)
10. [Deployment Architecture](#10-deployment-architecture)
11. [Risk Assessment](#11-risk-assessment)
12. [Appendices](#12-appendices)

---

## 1. Executive Summary

### 1.1 Purpose

The RAGG Debugger is a **local-first, high-performance static analysis engine** that transforms polyglot source code into a queryable **Semantic Knowledge Graph**. This graph serves as the foundation for:

- **Deterministic Tooling:** Code navigation, safe refactoring, linting, and dead code detection
- **Probabilistic Tooling:** RAG-backed context generation for LLMs to minimize hallucination during debugging and code generation tasks

### 1.2 Key Differentiators

| Aspect                 | Traditional IDEs             | RAGG Debugger                   |
| ---------------------- | ---------------------------- | ------------------------------- |
| **Language Support**   | Language-specific plugins    | Unified IR across all languages |
| **Analysis Scope**     | Single-file or project-local | Cross-project semantic analysis |
| **LLM Integration**    | Token-stuffing approaches    | Optimized semantic slicing      |
| **Refactoring Safety** | Heuristic-based              | Graph-proven correctness        |

### 1.3 Scope Boundaries

```mermaid
graph LR
    subgraph "In Scope"
        A[Static Analysis]
        B[Semantic Graphing]
        C[Code Navigation]
        D[Safe Refactoring]
        E[LLM Context Building]
        F[LSP Protocol Support]
    end

    subgraph "Out of Scope"
        G[Runtime Emulation]
        H[Binary Generation]
        I[Full Grammar Mapping]
        J[Cloud-First Architecture]
    end

    style A fill:#2d5a27
    style B fill:#2d5a27
    style C fill:#2d5a27
    style D fill:#2d5a27
    style E fill:#2d5a27
    style F fill:#2d5a27
    style G fill:#5a2727
    style H fill:#5a2727
    style I fill:#5a2727
    style J fill:#5a2727
```

---

## 2. System Vision & Goals

### 2.1 Vision Statement

> **"Transform any codebase into a queryable knowledge graph that enables both deterministic tooling and intelligent LLM-assisted development, operating entirely on local infrastructure."**

### 2.2 Primary Goals

| ID  | Goal                           | Success Metric                                            |
| --- | ------------------------------ | --------------------------------------------------------- |
| G1  | **Language Agnostic Analysis** | Support 10+ languages through unified adapter pattern     |
| G2  | **Sub-second Query Response**  | P95 latency < 100ms for navigation queries                |
| G3  | **Incremental Processing**     | Re-index only changed files, < 2s for typical edits       |
| G4  | **LLM Context Optimization**   | Generate semantically-optimal context within token budget |
| G5  | **Safe Refactoring**           | Zero false-positive refactoring proposals                 |

### 2.3 Architectural Principles

```mermaid
mindmap
  root((RAGG<br/>Principles))
    Graph_is_API
      All features query the graph
      Single source of truth
      Consistent view
    Lazy_Incremental
      Parse only changed files
      Re-analyze affected sub-graphs
      Minimize computation
    Graceful_Degradation
      Partial parsing continues
      Failed adapters isolated
      Always return some result
    Strict_Layering
      Adapters never depend on Graph
      One-way dependencies
      Clean interfaces
    Token_Budget_Awareness
      Max information per token
      Semantic prioritization
      Intelligent slicing
```

---

## 3. Architectural Overview

### 3.1 System Context Diagram (C4 Level 1)

```mermaid
C4Context
    title System Context Diagram - RAGG Debugger

    Person(developer, "Developer", "Uses IDE with LSP integration")
    Person(llm_user, "LLM User", "Requests code explanations via CLI")

    System(ragg, "RAGG Debugger", "Language-agnostic code intelligence engine")

    System_Ext(ide, "IDE", "VS Code, Neovim, etc.")
    System_Ext(llm, "LLM Provider", "Ollama, OpenAI, etc.")
    System_Ext(vcs, "Version Control", "Git repository")

    Rel(developer, ide, "Writes code")
    Rel(ide, ragg, "LSP Protocol")
    Rel(llm_user, ragg, "CLI commands")
    Rel(ragg, llm, "API calls with context")
    Rel(ragg, vcs, "Watches file changes")
```

### 3.2 Container Diagram (C4 Level 2)

```mermaid
graph TB
    subgraph "RAGG Debugger System"
        subgraph "Ingestion Layer"
            FSW[File System Watcher]
            AL[Adapter Layer]
            UIR[UIR Generator]
        end

        subgraph "Core Engine"
            SGC[Semantic Graph Core]
            AE[Analysis Engine]
            RE[Refactoring Engine]
        end

        subgraph "Storage Layer"
            KV[(KV Store<br/>RocksDB)]
            VEC[(Vector Store<br/>ChromaDB)]
            SQL[(Relational Index<br/>SQLite)]
            FS[(File Store<br/>Content-Addressed)]
        end

        subgraph "Presentation Layer"
            LSP[LSP Server]
            CLI[CLI Tool]
            LCB[LLM Context Builder]
        end
    end

    FSW --> AL
    AL --> UIR
    UIR --> SGC
    SGC --> KV
    SGC --> VEC
    SGC --> SQL
    SGC --> FS
    SGC --> AE
    AE --> RE
    SGC --> LSP
    SGC --> CLI
    SGC --> LCB

    style SGC fill:#4a90d9
    style AE fill:#4a90d9
```

### 3.3 High-Level Data Flow

```mermaid
sequenceDiagram
    participant FS as File System
    participant W as Watcher
    participant A as Adapter
    participant G as Graph Core
    participant S as Storage
    participant P as Presentation

    FS->>W: File Change Event
    W->>A: Delta (changed files)
    A->>A: Parse via Tree-sitter
    A->>A: Extract UIR Nodes/Edges
    A->>G: Upsert UIR
    G->>G: Update Graph Topology
    G->>S: Persist Changes
    G->>S: Update Embeddings

    Note over P: Query Phase
    P->>G: Query Request
    G->>S: Fetch from Storage
    G->>P: Query Results
```

---

## 4. Component Architecture

### 4.1 Component Overview

```mermaid
graph TB
    subgraph "File System Watcher"
        FSW1[inotify/FSEvents Handler]
        FSW2[Change Detector]
        FSW3[Delta Queue]
    end

    subgraph "Adapter Layer"
        AL1[Adapter Registry]
        AL2[Tree-sitter Parser Pool]
        AL3[Query Engine]
        AL4[Language Adapters]
    end

    subgraph "UIR Generator"
        UIR1[Node Factory]
        UIR2[Edge Factory]
        UIR3[Hash Computer]
    end

    subgraph "Semantic Graph Core"
        SGC1[Graph Manager]
        SGC2[Partition Manager]
        SGC3[Query Executor]
        SGC4[Transaction Manager]
    end

    subgraph "Analysis Engine"
        AE1[Symbol Resolver]
        AE2[Taint Analyzer]
        AE3[Complexity Calculator]
        AE4[Dead Code Detector]
    end

    subgraph "Refactoring Engine"
        RE1[Safety Validator]
        RE2[Patch Generator]
        RE3[Collision Detector]
    end

    FSW3 --> AL1
    AL1 --> AL2
    AL2 --> AL3
    AL3 --> UIR1
    UIR1 --> SGC1
    SGC1 --> AE1
    AE1 --> RE1
```

### 4.2 Component Responsibilities

| Component               | Primary Responsibility                        | Key Interfaces                   |
| ----------------------- | --------------------------------------------- | -------------------------------- |
| **File System Watcher** | Detect file changes, compute deltas           | `ChangeEvent`, `DeltaQueue`      |
| **Adapter Layer**       | Language-specific parsing to universal format | `LanguageAdapter`, `Parser`      |
| **UIR Generator**       | Create normalized intermediate representation | `UIRNode`, `UIREdge`             |
| **Semantic Graph Core** | Maintain and query the knowledge graph        | `GraphQuery`, `Transaction`      |
| **Analysis Engine**     | Static analysis passes over graph             | `AnalysisPass`, `AnalysisResult` |
| **Refactoring Engine**  | Safe code transformations                     | `RefactorRequest`, `Patch`       |
| **LLM Context Builder** | Optimize context for LLM consumption          | `ContextSlice`, `PromptBuilder`  |
| **LSP Server**          | IDE protocol implementation                   | JSON-RPC over stdio/TCP          |
| **CLI Tool**            | Command-line interface                        | Shell commands                   |

### 4.3 Graph Partition Strategy

The Semantic Graph is logically partitioned for query optimization:

```mermaid
graph LR
    subgraph "Semantic Graph Partitions"
        SCG[Static Call Graph<br/>Who calls whom]
        IG[Import Graph<br/>Module dependencies]
        DDG[Data Dependency Graph<br/>Def-Use chains]
        IHG[Inheritance Graph<br/>Class hierarchy]
    end

    SCG -.->|cross-ref| IG
    SCG -.->|cross-ref| DDG
    DDG -.->|cross-ref| IHG

    style SCG fill:#3d5a80
    style IG fill:#98c1d9
    style DDG fill:#e0fbfc
    style IHG fill:#ee6c4d
```

---

## 5. Data Architecture

### 5.1 Data Model Overview

```mermaid
erDiagram
    UIRNode ||--o{ UIREdge : "source"
    UIRNode ||--o{ UIREdge : "target"
    UIRNode ||--o| Embedding : "has"
    UIRNode }|--|| SourceFile : "belongs_to"

    UIRNode {
        string id PK "Content-addressable hash"
        string file_path
        enum kind "FUNCTION|CLASS|VAR|INTERFACE"
        string name
        string type_sig
        json range "start_line, end_line, etc."
        text docstring
        boolean is_exported
        json metadata
    }

    UIREdge {
        string src_id FK
        string dst_id FK
        enum kind "CALLS|IMPORTS|DEFINES|INHERITS"
        float weight "Relevance ranking"
    }

    Embedding {
        string node_id FK
        vector embedding "768/1536 dims"
        string model_version
    }

    SourceFile {
        string path PK
        string content_hash
        timestamp last_indexed
        int line_count
    }
```

### 5.2 Storage Layer Distribution

```mermaid
pie title Data Distribution Across Storage Engines
    "SQLite (Relational)" : 35
    "In-Memory Graph" : 25
    "ChromaDB (Vectors)" : 25
    "Content-Addressed FS" : 15
```

### 5.3 Hybrid Storage Strategy

| Data Category           | Storage Engine                | Access Pattern                     | Consistency |
| ----------------------- | ----------------------------- | ---------------------------------- | ----------- |
| **Node/Edge Metadata**  | SQLite                        | Random access by ID, range queries | Strong      |
| **Graph Topology**      | In-Memory (NetworkX/Petgraph) | Traversal, path finding            | Eventual    |
| **Semantic Embeddings** | ChromaDB/Faiss                | Vector similarity search           | Eventual    |
| **Source Blobs**        | Content-Addressed Files       | Version-agnostic retrieval         | Strong      |
| **File Hash Map**       | SQLite                        | Incremental change detection       | Strong      |

---

## 6. Integration Architecture

### 6.1 External Integration Points

```mermaid
graph TB
    subgraph "RAGG Debugger"
        CORE[Core Engine]
        LSP_S[LSP Server]
        CLI_S[CLI Interface]
        LLM_C[LLM Client]
    end

    subgraph "IDE Ecosystem"
        VSCODE[VS Code]
        NVIM[Neovim]
        JB[JetBrains IDEs]
    end

    subgraph "LLM Providers"
        OLLAMA[Ollama<br/>Local]
        OPENAI[OpenAI<br/>Cloud]
        ANTHRO[Anthropic<br/>Cloud]
    end

    subgraph "VCS"
        GIT[Git Hooks]
        GHACT[GitHub Actions]
    end

    VSCODE -.->|LSP| LSP_S
    NVIM -.->|LSP| LSP_S
    JB -.->|LSP| LSP_S

    LLM_C -.->|HTTP/REST| OLLAMA
    LLM_C -.->|HTTP/REST| OPENAI
    LLM_C -.->|HTTP/REST| ANTHRO

    GIT -.->|Events| CORE
    GHACT -.->|Webhooks| CORE
```

### 6.2 LSP Protocol Support

| LSP Method                | RAGG Implementation                            |
| ------------------------- | ---------------------------------------------- |
| `textDocument/definition` | Query Graph for `DEFINES` edge                 |
| `textDocument/references` | Query Graph for incoming `USES` edges          |
| `textDocument/rename`     | Trigger Refactoring Engine with safety checks  |
| `textDocument/hover`      | Return inferred type + docstring + LLM summary |
| `textDocument/completion` | Scope-aware symbol completion from graph       |
| `textDocument/codeAction` | Refactoring suggestions from Analysis Engine   |

### 6.3 LLM Integration Flow

```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant ContextBuilder
    participant Graph
    participant Vector
    participant LLM

    User->>CLI: codemap explain <symbol>
    CLI->>ContextBuilder: Build context for symbol
    ContextBuilder->>Graph: Get target function
    ContextBuilder->>Graph: Get 1-hop definitions (called functions)
    ContextBuilder->>Graph: Get 1-hop references (usage sites)
    ContextBuilder->>Graph: Get type definitions
    ContextBuilder->>Vector: Find similar code snippets
    ContextBuilder->>ContextBuilder: Optimize for token budget
    ContextBuilder->>LLM: Send structured prompt
    LLM->>ContextBuilder: Response
    ContextBuilder->>CLI: Formatted explanation
    CLI->>User: Display result
```

---

## 7. Technology Stack

### 7.1 Core Technology Decisions

```mermaid
graph TB
    subgraph "Language & Runtime"
        PY[Python 3.11+<br/>Prototype/MVP]
        RS[Rust<br/>Production Core]
    end

    subgraph "Parsing Infrastructure"
        TS[Tree-sitter<br/>Universal Parser]
        SCM[SCM Queries<br/>Syntax Mapping]
    end

    subgraph "Graph Processing"
        NX[NetworkX<br/>Python Prototype]
        PG[Petgraph<br/>Rust Production]
    end

    subgraph "Storage"
        SQL[SQLite<br/>Relational Metadata]
        CHROMA[ChromaDB<br/>Vector Search]
        ROCKS[RocksDB<br/>KV Store - Future]
    end

    subgraph "Protocol"
        LSPP[pygls/tower-lsp<br/>LSP Implementation]
        GRPC[gRPC<br/>Internal Comm]
    end

    style PY fill:#3776ab
    style RS fill:#dea584
    style TS fill:#6fba57
```

### 7.2 Technology Justification

| Component         | Choice              | Rationale                                | Alternatives Considered                   |
| ----------------- | ------------------- | ---------------------------------------- | ----------------------------------------- |
| **Parser**        | Tree-sitter         | Universal, incremental, battle-tested    | ANTLR (heavier), Custom (expensive)       |
| **Graph Library** | NetworkX → Petgraph | Fast iteration → Production perf         | Neo4j (heavyweight), DGraph (distributed) |
| **Relational DB** | SQLite              | Embedded, ACID, sufficient for 500k+ LOC | PostgreSQL (overkill), MySQL (overkill)   |
| **Vector Store**  | ChromaDB            | Python-native, simple API, good perf     | Faiss (lower-level), Pinecone (cloud)     |
| **LSP Framework** | pygls (Python)      | Mature, well-documented                  | tower-lsp (Rust - production)             |
| **Language**      | Python → Rust       | Prototype speed → Production performance | Go (less ecosystem), C++ (complexity)     |

### 7.3 Dependency Management

```yaml
# Core Dependencies (Python Prototype)
core:
  - tree_sitter >= 0.21.0 # Universal parser
  - tree_sitter_languages >= 1.8 # Pre-built grammars
  - networkx >= 3.2 # Graph data structure
  - chromadb >= 0.4.0 # Vector store
  - pygls >= 1.3.0 # LSP implementation
  - sqlalchemy >= 2.0 # Database ORM
  - pydantic >= 2.5 # Data validation
  - click >= 8.1 # CLI framework
  - watchdog >= 4.0 # File system events

analysis:
  - sentence_transformers >= 2.2 # Code embeddings

optional:
  - ollama >= 0.1.0 # Local LLM client
  - openai >= 1.0 # Cloud LLM client
```

---

## 8. Quality Attributes

### 8.1 Performance Requirements

| Metric                 | Target               | Measurement               |
| ---------------------- | -------------------- | ------------------------- |
| **Initial Index Time** | < 30s for 100k LOC   | Wall clock time           |
| **Incremental Update** | < 2s per file change | Hot path latency          |
| **Navigation Query**   | P95 < 100ms          | End-to-end LSP response   |
| **LLM Context Build**  | < 500ms              | Semantic slice generation |
| **Memory Footprint**   | < 2GB for 500k LOC   | RSS measurement           |

### 8.2 Scalability Targets

```mermaid
graph LR
    subgraph "Scale Tiers"
        T1[Tier 1<br/>< 100k LOC<br/>Single Dev]
        T2[Tier 2<br/>< 500k LOC<br/>Small Team]
        T3[Tier 3<br/>< 2M LOC<br/>Large Project]
        T4[Tier 4<br/>> 2M LOC<br/>Enterprise]
    end

    T1 -->|SQLite + In-Memory| T2
    T2 -->|Add RocksDB| T3
    T3 -->|Distributed Graph| T4

    style T1 fill:#4caf50
    style T2 fill:#8bc34a
    style T3 fill:#ffc107
    style T4 fill:#ff9800
```

### 8.3 Reliability & Fault Tolerance

| Scenario            | Handling Strategy                         |
| ------------------- | ----------------------------------------- |
| **Parse Failure**   | Graceful degradation - index rest of file |
| **Corrupted Index** | Automatic rebuild from source             |
| **Storage Full**    | LRU eviction for embeddings, reject new   |
| **LLM Timeout**     | Fallback to cached/static response        |
| **Crash Recovery**  | WAL-based SQLite persistence              |

---

## 9. Security Considerations

### 9.1 Security Boundaries

```mermaid
graph TB
    subgraph "Trust Boundary: Local System"
        FS[File System Access]
        DB[Local Database]
        MEM[Memory]
    end

    subgraph "Trust Boundary: External APIs"
        LLM_API[LLM Provider APIs]
    end

    subgraph "RAGG Engine"
        CORE[Core Engine]
    end

    FS -.->|Read-only by default| CORE
    DB -.->|Encrypted at rest| CORE
    CORE -.->|Anonymized prompts| LLM_API

    style LLM_API fill:#ff6b6b
```

### 9.2 Security Requirements

| Requirement               | Implementation                             |
| ------------------------- | ------------------------------------------ |
| **No Code Execution**     | Static analysis only, no `eval()`          |
| **Local-First**           | All processing on user's machine           |
| **API Key Management**    | System keychain integration                |
| **LLM Data Sanitization** | Strip secrets before sending to cloud LLMs |
| **Audit Logging**         | Optional logging for enterprise compliance |

---

## 10. Deployment Architecture

### 10.1 Deployment Models

```mermaid
graph TB
    subgraph "Model A: Standalone CLI"
        CLI_A[pip install ragg-debugger]
        CLI_A --> LOCAL_A[Local Files]
    end

    subgraph "Model B: IDE Extension"
        EXT_B[VS Code Extension]
        EXT_B --> LSP_B[Bundled LSP Server]
        LSP_B --> LOCAL_B[Local Files]
    end

    subgraph "Model C: Dev Container"
        DOCKER_C[Docker Image]
        DOCKER_C --> VOL_C[Mounted Volumes]
    end
```

### 10.2 Distribution Strategy

| Distribution Channel    | Package Format | Update Mechanism      |
| ----------------------- | -------------- | --------------------- |
| **PyPI**                | Wheel          | pip upgrade           |
| **VS Code Marketplace** | VSIX           | Extension auto-update |
| **Homebrew**            | Formula        | brew upgrade          |
| **Docker Hub**          | Image          | docker pull           |
| **GitHub Releases**     | Binary/Source  | Manual download       |

---

## 11. Risk Assessment

### 11.1 Technical Risks

| Risk                         | Probability | Impact | Mitigation             |
| ---------------------------- | ----------- | ------ | ---------------------- |
| Tree-sitter grammar gaps     | Medium      | High   | Custom query fallbacks |
| NetworkX performance ceiling | High        | Medium | Planned Rust migration |
| LLM API rate limiting        | Medium      | Low    | Local Ollama default   |
| Embedding model drift        | Low         | Medium | Versioned embeddings   |

### 11.2 Operational Risks

| Risk                       | Probability | Impact | Mitigation                |
| -------------------------- | ----------- | ------ | ------------------------- |
| Large monorepo performance | Medium      | High   | Incremental indexing      |
| Disk space exhaustion      | Low         | Medium | Configurable cache limits |
| Memory pressure            | Medium      | Medium | Streaming analysis        |

---

## 12. Appendices

### A. Glossary

| Term    | Definition                                                      |
| ------- | --------------------------------------------------------------- |
| **UIR** | Unified Intermediate Representation - normalized code structure |
| **SCG** | Static Call Graph - function call relationships                 |
| **DDG** | Data Dependency Graph - variable usage patterns                 |
| **LSP** | Language Server Protocol - IDE communication standard           |
| **RAG** | Retrieval-Augmented Generation - context-aware LLM prompting    |

### B. Referenced Documents

- [ragg_debugger_architecure.md](file:///home/sabawi/Development/RAICA/ragg_debugger_architecure.md) - Original architecture specification
- [RAGG_Debugger_LLD.md](file:///home/sabawi/Development/RAICA/RAGG_Debugger_LLD.md) - Low-Level Design (companion document)

### C. Revision History

| Version | Date       | Author                  | Changes              |
| ------- | ---------- | ----------------------- | -------------------- |
| 1.0     | 2026-01-18 | Senior Engineering Team | Initial HLD creation |

---

> [!NOTE]
> This HLD is intended for senior developers and architects. For implementation specifics, refer to the accompanying Low-Level Design (LLD) document.

The Raica agent CLI is a sophisticated terminal-based agentic system designed to bridge the gap between high-level reasoning and low-level system execution. Unlike typical "chat with your code" tools, it operates as an autonomous loop, treating the terminal as its primary interface to the machine.

When tackling a complex large-system issue (e.g., a race condition in a distributed microservice or a memory leak in a legacy C++ codebase), Raica agent follows a specific architectural pattern centered on Recursive Observation and Action.

## 1. High-Level Architecture

Raica agent is built on a "Reason-Act-Observe" cycle. It doesn't just predict the next token; it predicts the next tool call.

### The Three-Layer Stack

- **The Cognitive Engine (high thinking LLM)**: The "Brain" that handles long-range planning, code comprehension, and hypothesis generation. It utilizes "Extended Thinking" budgets (Think, Hard, Harder, Ultrathink) to simulate execution paths before writing a single line.
- **The Context Controller**: Manages the active context window. Since large systems exceed any model's limit, it uses Hierarchical Context Management. It reads RAICA.md for project rules and uses ripgrep or ls-R style tools to "crawl" the codebase on demand, rather than loading everything at once.
- **The Tool Execution Layer (The Limbs)**: This is where the CLI interacts with your OS. It includes:
  - **Filesystem Tools**: Atomic reads, partial file edits, and file creation.
  - **Command Tools**: Direct access to Bash/Zsh to run compilers, linters, and debuggers (GDB/LLDB).
  - **Dependency Resolver**: Dynamic LLM-driven mapping of Python imports to PyPI packages (see [Dependency Resolution Architecture](DEPENDENCY_RESOLUTION_ARCHITECTURE.md)).
  - **MCP (Model Context Protocol)**: A bridge to external data like Jira tickets, Slack logs, or GitHub PRs.

## 2. The Debugging Workflow: Deep Dive

When you feed Raica agent a complex system error, it moves through a specialized "Investigation and Remediation" workflow.

### Phase 1: Contextual Grounding & Exploration

Raica begins by identifying the "Blast Radius" of the issue.

- **Action**: It searches for the error string across the repository using grep or specialized search tools.
- **Architecture Detail**: It uses Lazy Loading. It doesn't read every file; it reads the RAICA.md root file up front, then follows imports recursively to build a mental map of relevant modules.

### Phase 2: Hypothesis Generation (Extended Thinking)

Instead of guessing, Raica enters a Planning Mode.

- **Workflow**: It creates a plan.md or a temporary checklist.
- **Technical Logic**: It uses "Internal Monologue" to weigh different causes.

### Phase 3: Forensic Probing

Raica will:

- **Instrument the code**: Insert console.log or printf statements.
- **Run the System**: Execute the build command and monitor the output stream.
- **Analyze Logs**: Tail log files and look for anomalies in real-time.

### Phase 4: Atomic Implementation & Verification

Once the bug is found:

- **Edit**: Surgical fixes using diff-based tooling.
- **Validate**: Automatically runs test suites. If tests fail, it views the stack trace as a new "Observation" and restarts the loop.

## 3. Key Technical Features

| Feature         | Function in Debugging                                                                  |
| --------------- | -------------------------------------------------------------------------------------- |
| Subagents       | Spawns "specialist" instances to investigate sub-directories or run tests in parallel. |
| Agent Skills    | Reusable scripts for deterministic, high-compute tasks.                                |
| Vibe Mode       | Autonomous loop for repetitive refactoring until the task is complete.                 |
| MCP Integration | Pulls external telemetry (e.g., CloudWatch logs) directly into context.                |

## 4. Architectural Guardrails

- **Permission Handshakes**: Asks for permission before running potentially "dangerous" shell commands.
- **Read-Only Planning**: "Research First" mode where it can only use read tools until approved.

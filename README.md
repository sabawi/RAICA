# RAICA - RAG AI Context Agency v1.0.0.168

An advanced AI-powered server with multi-LLM orchestration, tool calling, document processing, vision capabilities, intelligent email management, **SEC regulatory filings**, **academic research integration**, and **extensible plugin system**.

[![Version](https://img.shields.io/badge/version-1.0.0.168-blue)](https://github.com/sabawi/RAICA/releases/tag/v1.0.0.168)
[![Python](https://img.shields.io/badge/python-3.13-green)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Installation](https://img.shields.io/badge/installation-automated-brightgreen)](install.sh)

## 🚀 Features

- **🔬 NEW: Deep Research Mode**: Auto-detected for thorough/comprehensive requests — plans sub-questions, searches many sources over multiple rounds, grades source credibility, synthesizes across multiple models with arbitration, and verifies every claim against the gathered evidence. Streams live progress and an answer with a source-credibility + claim-verification audit.
- **⚙️ NEW: POST-LLM Workflow Engine**: Executes complex, multi-step tasks like file creation and email sending *after* the primary LLM has generated its final, polished response.
- **🔌 NEW: Plugin System**: Create custom LLM tools in 5 minutes - just 2 files (YAML + Python)
- **🚀 Intelligent Email Management**: Advanced email retrieval and optimization with 84% context reduction
- **Multi-LLM Architecture**: Primary, tool-calling, arbitration, and vision models working together
- **OpenAI-Compatible API**: Full compatibility with OpenAI client libraries
- **Vision Processing**: Image analysis and OCR capabilities with qwen2.5vl:3b
- **Document Intelligence**: FAISS-powered document store with EasyOCR integration
- **Tool Calling System**: Extensible user tools for calendar, email, web scraping, and more
- **Real-time Streaming**: Support for streaming responses
- **Auto-fallback**: Automatic failover between LLM providers
- **HTML Content Optimization**: Revolutionary HTML-to-text conversion with formatting preservation

## 📚 Documentation

### Production Documentation (V1.0)
- **[Installation Guide](docs/production/INSTALLATION_GUIDE.md)** - Automated installation system
- **[Administrator Guide](docs/production/ADMINISTRATOR_GUIDE.md)** - System administration and maintenance
- **[User Guide](docs/production/USER_GUIDE.md)** - API usage and features
- **[Developer Guide](docs/production/DEVELOPER_GUIDE.md)** - Development and architecture

### Quick Reference
- **[Main Documentation Hub](docs/README.md)** - Central navigation and overview
- **[POST-LLM Execution Architecture](docs/POST_LLM_EXECUTION_ARCHITECTURE.md)** - 🆕 Critical: Multi-step workflow execution system
- **[Email Workflow Best Practices](docs/production/EMAIL_WORKFLOW_GUIDE.md)** - 🆕 Smart email routing patterns and limitations
- **[CLI Model Management](docs/CLI_MODEL_MANAGEMENT.md)** - 🆕 Easy model switching and configuration
- **[News Sources Configuration](docs/NEWS_SOURCES_CONFIGURATION.md)** - Customize news sources without code changes

## 🤖 Pre-Built Intelligent Agents

Explore **production-ready agent examples** in the `./agents` directory showcasing the server's powerful capabilities:

### Featured Agents
- **[Business Intelligence Agent](agents/business_intelligence/)** - Automated strategic analysis with market research, financial analysis, competitor intelligence, and executive reporting
- **[Stock Monitor Agent](agents/stock_monitor/)** - Real-time portfolio monitoring with price alerts and automated email notifications
- **[News Retriever Agent](agents/news_retriever/)** - Multi-source news aggregation with intelligent summarization
- **[Market Sentiment Agent](agents/market_sentiment/)** - Financial market sentiment analysis and trend detection
- **[Social Media Tracker](agents/social_media_tracker/)** - Social media monitoring and engagement analytics
- **[Document Intelligence Agent](agents/document_intelligence/)** - Document analysis and insight extraction
- **[Email Digest Agent](agents/email_digest/)** - Smart email summarization and priority detection
- **[Research Assistant Agent](agents/research_assistant/)** - Academic research with paper search and synthesis

### Getting Started with Agents
```bash
# Explore available agents
cd agents
ls -l

# Run a specific agent (example: Business Intelligence)
cd business_intelligence
./business_intelligence.py --test

# View agent documentation
cat README.md
```

**Key Features Demonstrated:**
- Multi-tool orchestration (news, web search, stock data, documents)
- Automated scheduling and monitoring
- Professional HTML report generation
- Email delivery integration
- Data visualization and charts
- Graceful error handling and retry logic

**Learn More**: See [agents/README.md](agents/README.md) for the complete agent catalog and development guide.

## 🚀 Quick Start

### Automated Installation (Recommended)
```bash
# Clone the repository
git clone https://github.com/sabawi/RAICA.git
cd RAICA

# Run the automated installer
./install.sh

# Start the server
./start_complete.sh
```

### Manual Installation
```bash
# See docs/production/INSTALLATION_GUIDE.md for complete setup
pip install -r requirements.txt
python fastapi_server_complete.py
```

## ⭐ About RAICA v1.0.0.168

RAICA (RAG AI Context Agency) is a fork of the Agentic-RAG-System, designed as a clean starting point for building intelligent AI-powered applications.

### Key Capabilities

- **Multi-LLM Orchestration**: Primary, tool-calling, arbitration, and vision models working in harmony
- **Autonomous Agents**: 10+ production-ready agents for business intelligence, research, and automation
- **Document Intelligence**: FAISS-powered document processing with semantic search
- **Vision Processing**: Image analysis and OCR with Qwen2.5vl integration
- **POST-LLM Workflow Engine**: Complex multi-step task execution after LLM response
- **Extensible Plugin System**: Create custom tools with just 2 files (YAML + Python)

### Getting Started

After installation, the server provides:
- OpenAI-compatible API endpoints
- Real-time streaming responses
- Automatic failover between LLM providers
- Comprehensive tool calling system

---

## ⭐ Core Features (Inherited from v1.0.3.123)

### 🚀 Enhanced Data Collection System - Option 2 Implementation

**v1.0.3.43** introduces three major data collection enhancements providing institutional-quality data at zero cost:

#### 🏛️ SEC EDGAR Integration - Official Regulatory Filings

Access the official SEC database for comprehensive regulatory filings from all publicly traded companies:

**Features:**
- **Filing Types**: 10-K (annual), 10-Q (quarterly), 8-K (events), Form 4 (insider trading), 13-F (holdings)
- **Free & Unlimited**: No API key required, 100% free access to SEC public data
- **Smart Caching**: 7 days for company identifiers, 24 hours for filings (performance optimized)
- **Rate Limit Compliant**: Automatic rate limiting (10 req/sec) per SEC guidelines
- **CIK Lookup**: Automatic ticker → CIK mapping with fallback methods

**Usage Examples:**
```python
# Get latest SEC filings for Tesla
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Get the latest SEC filings for Tesla (TSLA)"}]
)

# Analyze specific filing types
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Get the last 3 10-K and 8-K filings for Apple and summarize key events"}]
)

# Extract financial data from 10-Q
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Get NVIDIA's most recent 10-Q filing and extract revenue, earnings, and cash flow numbers"}]
)
```

**Configuration:** Enable in `config/feature_flags.py`:
```python
ENABLE_SEC_EDGAR = True  # Default: Enabled
```

**Behind the Scenes:**
- Files: `utils/sec_edgar_client.py`, `user_tools/sec_edgar_tool.py`, `config/edgar_config.py`
- Caching: `.cache/sec_edgar/` directory (automatic TTL management)
- Data Source: https://data.sec.gov (official SEC API)

---

#### 🎓 Academic Research Integration - Multi-API Paper Search

Search across three major academic databases with intelligent auto-domain detection:

**Features:**
- **Semantic Scholar**: Citation-ranked papers with impact metrics (100 req/5 min free tier)
- **arXiv**: CS/Math/Physics preprints, unlimited free access
- **PubMed**: 35M+ biomedical research articles (3 req/sec free tier)
- **Auto-Domain Detection**: AI/ML queries → arXiv+Semantic Scholar, Medical queries → PubMed
- **Parallel Search**: Concurrent API calls for faster results
- **Citation Ranking**: Papers sorted by citation count and impact
- **Deduplication**: Title similarity matching to remove duplicates across sources

**Usage Examples:**
```python
# AI/ML research (auto-selects arXiv + Semantic Scholar)
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Search for the latest academic papers on transformer models and summarize key findings"}]
)

# Medical research (auto-selects PubMed + Semantic Scholar)
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Find recent research papers on mRNA vaccine efficacy"}]
)

# Specific topic with limit
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Search for 10 most cited papers on quantum computing from the last 2 years"}]
)
```

**Configuration:** Enable in `config/feature_flags.py`:
```python
ENABLE_ACADEMIC_RESEARCH = True  # Default: Enabled
ACADEMIC_RESEARCH_SEMANTIC_SCHOLAR = True  # Individual source toggles
ACADEMIC_RESEARCH_ARXIV = True
ACADEMIC_RESEARCH_PUBMED = True
```

**Behind the Scenes:**
- Files: `utils/academic_research_client.py`, `user_tools/research_paper_search.py`, `config/academic_config.py`
- Caching: 1 hour TTL for research results
- APIs: Semantic Scholar (JSON), arXiv (XML/Atom), PubMed E-utilities (XML)

---

#### 📰 Enhanced RSS Processing - Google News + Content Extraction

Dramatically improved news collection with premium sources and full article extraction:

**Features:**
- **Google News Integration**: Free, unlimited news aggregation from Google News RSS
- **Full Article Content**: newspaper3k + BeautifulSoup fallback extracts complete articles
- **118 Premium Sources** (+38 new sources):
  - **Breaking News Wire**: Reuters (8 categories), AP News
  - **In-Depth Analysis**: Financial Times (7 feeds), Barron's, Wall Street Journal
  - **Academic/Research**: Nature, Science Magazine, MIT Tech Review, Scientific American
  - **Policy Analysis**: Brookings Institution, Foreign Policy, The Atlantic, VoxEU
  - **Tech Industry**: The Verge, The Information, TechCrunch
- **Smart Deduplication**: 3-level system (URL normalization, title similarity 80%, content hash)
- **Sentiment Analysis**: Optional textblob/VADER sentiment scoring
- **Context Engineering**: All outputs in SOURCE block format for perfect citations

**Usage Examples:**
```bash
# Get latest news on specific topic
curl -X POST http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "RAICA-Model1",
    "messages": [{"role": "user", "content": "Get latest news on artificial intelligence"}]
  }'

# Financial news from premium sources
curl -X POST http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "RAICA-Model1",
    "messages": [{"role": "user", "content": "Get latest financial market news from Reuters and Financial Times"}]
  }'
```

**Customizing News Sources:**

Edit `config/news_sources.yaml` to add/remove RSS feeds:

```yaml
news_sources:
  finance:
    - https://www.reuters.com/markets/rss  # Reuters markets wire
    - https://www.ft.com/markets?format=rss  # Financial Times markets
    - https://your-custom-feed.com/rss  # Add your own!

  technology:
    - https://www.reuters.com/technology/rss
    - https://techcrunch.com/feed/
    - https://your-tech-blog.com/feed  # Custom tech source

  # Add new category
  climate:
    - https://www.carbonbrief.org/feed/
    - https://insideclimatenews.org/feed/
```

**Changes take effect immediately** - no server restart required!

**Configuration:** Enable in `config/feature_flags.py`:
```python
ENABLE_ENHANCED_RSS = True  # Default: Enabled
ENHANCED_RSS_GOOGLE_NEWS = True  # Google News integration
ENHANCED_RSS_CONTENT_EXTRACTION = True  # Full article extraction
ENHANCED_RSS_SENTIMENT_ANALYSIS = True  # Sentiment scoring
```

**News Sources Configuration Guide:**

1. **Edit config/news_sources.yaml**:
   - Each category (world, business, finance, technology, etc.) has a list of RSS feed URLs
   - Add new feeds by inserting new URLs with `- https://...` format
   - Remove feeds by deleting or commenting out lines with `#`

2. **Category Mapping** (optional):
   - Edit `category_mapping` section to customize keyword detection
   - Add `primary_terms`, `secondary_terms`, `compound_phrases` for your topics
   - Adjust `weight` values (0.0 to 1.0) for category priority

3. **Keyword Mappings** (optional):
   - Edit `keyword_mappings` section for exact phrase → category mapping
   - Example: `"machine learning": [technology, science]`

4. **Test Your Changes**:
   ```bash
   # Test with a query
   curl -X POST http://localhost:5000/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "RAICA-Model1",
       "messages": [{"role": "user", "content": "Get latest news on [your topic]"}]
     }'
   ```

**Behind the Scenes:**
- Files: `utils/enhanced_rss_processor.py`, `config/rss_config.py`, `config/news_sources.yaml`
- Caching: 6 hours for extracted article content
- Rate Limiting: 150ms between content extraction requests

---

### 📊 Impact Summary v1.0.3.43

**Zero Cost, Institutional Quality Data:**
- ✅ SEC EDGAR: Official regulatory filings (was: unavailable)
- ✅ Academic Research: 3 free APIs (was: web search only)
- ✅ Enhanced News: 118 premium sources (was: 80, +48% increase)
- ✅ Google News: Unlimited free aggregation
- ✅ Full Article Content: newspaper3k extraction (was: headlines only)
- ✅ Smart Deduplication: 3-level system (was: basic URL matching)
- ✅ **Total Cost: $0/month** for 7 APIs and 118 news sources

**Files Added:**
- `utils/sec_edgar_client.py` (270 lines)
- `utils/sec_filing_cache.py` (159 lines)
- `utils/academic_research_client.py` (570 lines)
- `utils/enhanced_rss_processor.py` (409 lines)
- `user_tools/sec_edgar_tool.py` (220 lines)
- `user_tools/research_paper_search.py` (185 lines)
- `config/edgar_config.py` (67 lines)
- `config/academic_config.py` (160 lines)
- `config/rss_config.py` (150 lines)
- Test files: `test_sec_edgar_integration.py`, `test_academic_research_integration.py`, `test_enhanced_rss_integration.py`

**Configuration Files Modified:**
- `config/feature_flags.py` - Added 3 new feature flags
- `config/news_sources.yaml` - Added 38 premium sources across 12 categories

**Dependencies:**
- No new dependencies required - uses existing packages (feedparser, newspaper3k, beautifulsoup4)

---

## ⭐ Key Technical Highlights

- **POST-LLM Workflow Engine**: Advanced execution of file and email tasks after LLM generates responses
- **Vision Model Integration**: Full base64 image processing with cloud and local vision models
- **Smart Email Routing**: Intelligent detection between PRE-LLM and POST-LLM email workflows
- **Citation System**: Standardized URL citations across all research and news tools
- **Plugin Architecture**: 5-minute tool creation with just YAML + Python

---

## 🧪 API Testing

Once installed, test the API:
```bash
# Test basic connectivity
curl http://localhost:5000/health

# Test chat completion
curl -X POST http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "RAICA-Model1", "messages": [{"role": "user", "content": "Hello!"}]}'
```

## 🏗️ Architecture

### LLM Stack
- **Primary Model**: `deepseek-v3.1:671b-cloud` (Local Ollama - conversation & reasoning)
- **Tool Calling**: `gpt-4o-mini` (OpenAI API - tool orchestration)*  
- **Vision Model**: `qwen2.5vl:3b` (Local Ollama - image analysis)
- **Arbitrator**: Configurable (Decision making)

*\* Tool calling requires OpenAI API key. See installation guide for setup.*

### Available Models
- **RAICA-Model1**: Primary agentic model with full tool access
- **RAICA-Model2**: Enhanced model for complex reasoning tasks

The system automatically handles multi-model orchestration internally, using local Ollama models for conversation and cloud models for specialized tool calling when needed.

### Core Components
- **FastAPI Server**: OpenAI-compatible REST API
- **Ollama Integration**: Local model serving
- **FAISS Document Store**: Vector-based document retrieval
- **Tool System**: Extensible Python tools
- **Multi-provider**: OpenAI, Gemini, Qwen fallback support

## 🛠️ Available Tools

- **📅 Calendar**: Google Calendar integration
- **📧 Email Retrieval**: 🚀 NEW: Advanced email retrieval with HTML optimization (Gmail, Outlook, Yahoo, iCloud)
- **📧 Email Sending**: Professional SMTP email sending with attachments
- **🌐 Web Scraping**: Content extraction and analysis
- **📄 Document Processing**: OCR and text extraction with FAISS indexing
- **🗂️ File Operations**: Local file management and processing
- **🖼️ Image Analysis**: Vision processing with OCR capabilities
- **🔍 Search**: Web search and academic paper retrieval
- **📊 Financial Tools**: Stock analysis and market data retrieval
- **📰 News Analysis**: Real-time news gathering and summarization from 118 premium sources
- **🏛️ SEC EDGAR**: 🆕 Official regulatory filings (10-K, 10-Q, 8-K, Form 4, 13-F) - Free, unlimited access
- **🎓 Academic Research**: 🆕 Multi-API paper search (Semantic Scholar, arXiv, PubMed) with citation ranking
- **📡 Enhanced RSS**: 🆕 Google News integration with full article content extraction

## 🏆 Competitive Advantages

| Feature | **RAICA v1.0** | **LangChain** | **LlamaIndex** | **Haystack** |
|---------|------------------------------|---------------|----------------|--------------|
| **Multi-Model Orchestration** | 🟢 Built-in arbitrator + multi-LLM routing | ⚪ Manual routing/dev-built | ⚪ Index-focused | ⚪ Single-LLM default |
| **Autonomous Tool Planning** | 🟢 19-tool system + GPT-4o orchestration | 🟢 ReAct/agent patterns | ⚪ Limited | ⚪ Static pipelines |
| **Production-Ready Setup** | 🟢 Automated install.sh + deployment | ⚪ Dev assembly required | ⚪ Dev assembly required | 🟢 Deployment guidance |
| **OpenAI API Compatibility** | 🟢 Full compatibility (drop-in replacement) | ⚪ SDK/API only | ⚪ SDK/API only | ⚪ API & tooling |
| **Multimodal RAG** | 🟢 Vision/OCR + multimodal built-in | ⚪ Glue code required | ⚪ Some loaders | ⚪ Limited multimodal |
| **Real-time Document Processing** | 🟢 Background scanning + auto-indexing | ⚪ Custom implementation | ⚪ Custom implementation | ⚪ Pipeline-based |
| **Built-in Monitoring** | 🟢 Arbitrator validation + integrity checks | ⚪ Needs LangSmith/3rd party | ⚪ Limited eval hooks | ⚪ Some Studio monitoring |
| **Enterprise Ready** | ⚪ Foundations (logging) - hardening recommended | ⚪ Dev responsibility | ⚪ Not core | ⚪ Limited enterprise features |

**Key Differentiators:**
- ✅ **Zero-Config Agentic Behavior**: Works out-of-the-box with autonomous tool selection
- ✅ **Revolutionary Email Optimization**: 84% context reduction with HTML-to-text conversion
- ✅ **Hybrid Local+Cloud**: Best of both worlds - privacy + power
- ✅ **True OpenAI Drop-in**: Existing OpenAI code works immediately
- ✅ **Production Focus**: From prototype to production in minutes
- ✅ **Intelligent Content Processing**: Advanced HTML optimization preserves meaning while reducing noise

## 🚀 Impressive Demo Examples

Experience the power of autonomous AI agents! These examples showcase real agentic behavior where the AI automatically selects and uses the right tools.

### 🌟 Start Simple

```bash
# Get latest news with web search
curl -X POST http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "RAICA-Model1",
    "messages": [{"role": "user", "content": "What is the latest news as of now?"}]
  }'
```

### 🎓 Academic Research

```bash
# AI automatically searches academic papers and summarizes findings
curl -X POST http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "RAICA-Model1",
    "messages": [{"role": "user", "content": "Search for the latest academic papers on Transformer enhancements in AI and summarize the key findings for me"}]
  }'
```

### 📊 Financial Analysis & Visualization

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:5000/v1", api_key="not-required")

# AI performs comprehensive stock analysis with charts and investment recommendations
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Using the provided research tool, look up available company and financial data on AMZN stock then:\n1.  Plot the stock chart for the last year and highlight percent change\n    \n2.  Perform full and thorough analysis on it's potential for growth and profit, and make reasoned recommendations whether to Buy, Hold, or Sell its stock for the next 6 months to 2 years investment horizon.\n    \n3.  In your conclusion, state clearly your final recommendation and why."}]
)
```

### 💹 Comprehensive Investment Analysis

```bash
# AI performs deep financial research and provides investment recommendations
curl -X POST http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "RAICA-Model1",
    "messages": [{"role": "user", "content": "Using the provided research tool, look up available company and financial data on MRNA, AMGN, JNJ stocks and perform full and thorough analysis on its potential for growth and profit, and make reasoned recommendations whether to Buy, Hold, or Sell its stock for the next 6 months to 2 years investment horizon. In your conclusion, state clearly your final recommendation and why."}]
  }'
```

### 📊 Statistical & Mathematical Visualizations

```python
# AI creates advanced statistical visualizations with annotations
from openai import OpenAI

client = OpenAI(base_url="http://localhost:5000/v1", api_key="not-required")

response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "What is the difference between normal distribution and binomial distribution. Plot both distributions side by side and add annotation and segmentation of probabilities through background colors"}]
)
```

### 📈 Mathematical Function Plotting

```python
# AI generates mathematical function plots with proper scaling and labels
from openai import OpenAI

client = OpenAI(base_url="http://localhost:5000/v1", api_key="not-required")

response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Create a Plot for the equation y=3x³-2x²-10x+10"}]
)
```

### 🔍 Smart Document Search

```python
# AI searches through your local documents intelligently
response = client.chat.completions.create(
    model="RAICA-Model1", 
    messages=[{"role": "user", "content": "Find documents about server configuration and summarize the key security settings I should know about"}]
)
```

### ✈️ Travel Planning

```python
# AI searches flights, compares prices, provides booking links
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Find flights from New York to London for next month, compare prices from different airlines, and show me the best options"}]
)
```

### 📧 Smart Email Management & Communication

```python
# 🚀 NEW: Advanced Email Retrieval with HTML Optimization
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Summarize my last 5 emails from Gmail and highlight any urgent items"}]
)

# AI composes and sends professional emails
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Send a professional email to sarah@company.example about scheduling a project review meeting next week. Include availability options and meeting agenda."}]
)
```

### 📊 Email Analytics & Processing

```bash
# AI analyzes email patterns and provides insights
curl -X POST http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "RAICA-Model1",
    "messages": [{"role": "user", "content": "Find all unread emails from work about the quarterly review and create a summary report"}]
  }'
```

### 📅 Calendar Integration

```python
# AI manages your calendar intelligently  
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "Check my calendar for next week and schedule a 2-hour team planning meeting when everyone is free. Send calendar invites to the team."}]
)
```

### 🖼️ Image Analysis & OCR

```python
# AI analyzes images and extracts information
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{
        "role": "user", 
        "content": [
            {"type": "text", "text": "Analyze this document image and extract all the key information into a structured summary"},
            {"type": "image_url", {"image_url": {"url": "file:///path/to/document.jpg"}}}
        ]
    }]
)
```

### 👤 AI-Powered Age Analysis

```bash
# AI analyzes faces and estimates age with remarkable accuracy
curl -X POST http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "RAICA-Model1",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "Analyse this image and Guess the age of this person (no description, just guess the age only)"},
        {"type": "image_url", {"image_url": {"url": "file:///path/to/selfie.jpg"}}}
      ]
    }]
  }'
```

### 🧮 Code Execution & Analysis

```python
# AI writes and executes code to solve problems
response = client.chat.completions.create(
    model="RAICA-Model2",
    messages=[{"role": "user", "content": "Calculate the optimal portfolio allocation for these 5 stocks based on historical data, run a Monte Carlo simulation, and create a risk analysis report"}]
)
```

### 📊 Mathematical Visualization

```bash
# AI creates sophisticated mathematical plots and visualizations
curl -X POST http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "RAICA-Model1",
    "messages": [{"role": "user", "content": "plot typical power curve and typical S-curve side by side"}]
  }'
```

### 🎯 Custom Mathematical Functions

```python
# AI plots complex mathematical functions with automatic analysis
response = client.chat.completions.create(
    model="RAICA-Model1",
    messages=[{"role": "user", "content": "plot y = 500/(1+e^-0.3*(x-200))"}]
)
```

## 🎯 What Makes This Special

**🤖 Autonomous Agent Behavior**: The AI decides which tools to use and chains them together automatically
- No manual tool specification required
- Intelligent task decomposition
- Multi-step reasoning and execution

**🔗 Tool Chaining**: Watch the AI use multiple tools in sequence:
1. Search for recent papers → Analyze findings → Summarize insights
2. Get stock data → Perform analysis → Create visualizations → Generate report
3. Search documents → Extract relevant info → Compose professional response

**🧠 Context Awareness**: The AI maintains context across tool calls and provides coherent final answers

## ⚙️ System Requirements

- **OS**: Linux (Ubuntu 20.04+)
- **RAM**: 16GB+ (8GB minimum)
- **Storage**: 50GB+ for models
- **Python**: 3.11+
- **Docker**: Optional for containerized deployment

## 📊 Monitoring & Logs

### Service Mode (Recommended)
```bash
# View real-time service logs
sudo journalctl -u agentic-rag-server -f

# View recent logs
sudo journalctl -u agentic-rag-server -n 100

# Check service status
sudo systemctl status agentic-rag-server

# Health check
curl http://localhost:5000/health
```

### Manual Mode
```bash
# Server logs
tail -f logs/server_complete.log

# Ollama service
journalctl -u ollama -f
```

### Service Management
```bash
# Start/stop/restart service
sudo systemctl start agentic-rag-server
sudo systemctl stop agentic-rag-server  
sudo systemctl restart agentic-rag-server

# Install/uninstall service
./install_service.sh
./uninstall_service.sh
```

## 🔒 Security

- Store API keys in `.env` file (never commit)
- Run behind reverse proxy in production
- Implement proper authentication
- Restrict network access appropriately

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Test changes (`python test_dependencies.py`)
4. Commit changes (`git commit -m 'Add amazing feature'`)
5. Push to branch (`git push origin feature/amazing-feature`)
6. Open Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📝 Version History

RAICA v1.0.0.168 is the latest release, forked from Agentic-RAG-System v1.0.3.123.

All features from the parent project are included. See the [Agentic-RAG-System](https://github.com/sabawi/Agentic-RAG-System) repository for historical changelog.

## 🆘 Support

- **Documentation**: Check the guides above
- **Issues**: Report bugs via [GitHub Issues](https://github.com/sabawi/RAICA/issues)
- **Discussions**: Use [GitHub Discussions](https://github.com/sabawi/RAICA/discussions) for questions
- **Logs**: Always check `logs/server_complete.log` first

## 🙏 Acknowledgments

- [Ollama](https://ollama.com) for local model serving
- [FastAPI](https://fastapi.tiangolo.com) for the web framework
- [OpenAI](https://openai.com) for API standards
- [FAISS](https://faiss.ai) for vector search
- [EasyOCR](https://github.com/JaidedAI/EasyOCR) for optical character recognition

---

**Quick Links**: [Installation](docs/production/INSTALLATION_GUIDE.md) | [User Guide](docs/production/USER_GUIDE.md) | [Admin Guide](docs/production/ADMINISTRATOR_GUIDE.md) | [Developer Guide](docs/production/DEVELOPER_GUIDE.md) | [Docs Hub](docs/README.md)
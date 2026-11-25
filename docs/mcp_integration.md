# MCP Integration Guide

## Overview

ContextForge includes a **Model Context Protocol (MCP)** server that enables direct integration with AI assistants like **Claude Desktop** and **Cursor**. The MCP server exposes ContextForge's RAG capabilities as tools that LLMs can invoke natively.

## What is MCP?

The **Model Context Protocol** is an open standard for connecting AI assistants to external tools and data sources. It defines:
- **Transport**: How client and server communicate (stdio, SSE, WebSocket)
- **Capabilities**: What the server can do (tools, resources, prompts)
- **Schema**: JSON Schema for tool parameters and return values

## Quick Start

### 1. Install ContextForge MCP Server

```bash
# From PyPI (when published)
pip install contextforge-mcp

# Or from source
cd contextforge
uv run python -m contextforge.mcp.server
```

### 2. Configure Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "contextforge": {
      "command": "uv",
      "args": ["run", "contextforge-mcp"],
      "env": {
        "CONTEXTFORGE_API_URL": "http://localhost:8000",
        "CONTEXTFORGE_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

### 3. Configure Cursor

In Cursor Settings → MCP Servers, add:

```json
{
  "name": "contextforge",
  "command": "uv",
  "args": ["run", "contextforge-mcp"],
  "env": {
    "CONTEXTFORGE_API_URL": "http://localhost:8000",
    "CONTEXTFORGE_API_KEY": "your-api-key-here"
  }
}
```

### 4. Restart Client

Restart Claude Desktop or Cursor. You should see ContextForge tools available.

---

## Available Tools

The MCP server exposes 6 tools:

### 1. `ingest_document`

Ingest a document into ContextForge for future retrieval.

**Parameters**:
```json
{
  "source_type": "text",           // Required: "text", "file", "url", "notion", "confluence", "github", "slack"
  "source_id": "unique-id",        // Required: Unique identifier within source
  "content": "Document content",   // Required for "text" source_type
  "source_url": "https://...",     // Optional: Original URL
  "title": "Document Title",       // Optional
  "strategy": "semantic",          // Optional: "semantic", "hierarchical", "code", "fixed"
  "embedding_provider": "openai",  // Optional: "openai", "azure", "bedrock", "local"
  "embedding_model": "text-embedding-3-large", // Optional
  "metadata": {},                  // Optional: Custom metadata
  "chunk_size": 512,               // Optional
  "chunk_overlap": 50              // Optional
}
```

**Returns**:
```json
{
  "job_id": "uuid",
  "status": "pending",
  "message": "Ingestion job queued"
}
```

**Example Usage in Claude**:
> "Ingest this API documentation into ContextForge so I can query it later."

### 2. `query_knowledge`

Search the knowledge base using hybrid search (vector + keyword).

**Parameters**:
```json
{
  "query": "How to configure rate limiting?",  // Required
  "top_k": 10,                                 // Optional: default 10, max 100
  "filters": {                                 // Optional
    "source_type": "file",
    "tags": ["api", "config"],
    "date_from": "2024-01-01",
    "date_to": "2024-12-31"
  },
  "score_threshold": 0.7,                      // Optional
  "search_type": "hybrid",                     // Optional: "hybrid", "vector", "keyword"
  "alpha": 0.5                                 // Optional: hybrid weight (0=keyword, 1=vector)
}
```

**Returns**:
```json
{
  "query": "How to configure rate limiting?",
  "results": [
    {
      "chunk_id": "uuid",
      "document_id": "uuid",
      "content": "Rate limiting is configured via...",
      "score": 0.92,
      "metadata": {
        "source_type": "file",
        "chunk_index": 3,
        "strategy": "semantic"
      }
    }
  ],
  "total_results": 42,
  "latency_ms": 45,
  "search_type": "hybrid"
}
```

**Example Usage in Claude**:
> "Search my knowledge base for information about rate limiting configuration."

### 3. `list_documents`

List ingested documents with pagination.

**Parameters**:
```json
{
  "page": 1,              // Optional: default 1
  "page_size": 20,        // Optional: default 20, max 100
  "source_type": "file"   // Optional: filter by source type
}
```

**Returns**:
```json
{
  "items": [
    {
      "id": "uuid",
      "source_type": "file",
      "source_id": "doc-123",
      "title": "API Documentation",
      "chunk_count": 42,
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 20,
  "total_pages": 8
}
```

### 4. `run_retrieval_eval`

Execute retrieval evaluation against a golden dataset.

**Parameters**:
```json
{
  "name": "weekly-retrieval-eval",    // Required
  "dataset": "golden_set_v1",         // Required
  "k_values": [1, 3, 5, 10, 20],     // Optional
  "config": {                         // Optional
    "search_type": "hybrid",
    "alpha": 0.5
  }
}
```

**Returns**:
```json
{
  "run_id": "uuid",
  "status": "running",
  "message": "Evaluation started"
}
```

### 5. `run_generation_eval`

Execute generation evaluation (RAGAS, LLM-as-Judge).

**Parameters**:
```json
{
  "name": "generation-quality-eval",    // Required
  "dataset": "golden_set_v1",           // Required
  "metrics": [                          // Optional
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall"
  ],
  "llm_judge_config": {                 // Optional
    "model": "gpt-4",
    "criteria": ["correctness", "completeness", "conciseness"]
  }
}
```

### 6. `get_eval_results`

Retrieve evaluation results by run ID.

**Parameters**:
```json
{
  "run_id": "uuid"    // Required
}
```

**Returns**:
```json
{
  "run_id": "uuid",
  "name": "weekly-retrieval-eval",
  "eval_type": "retrieval",
  "dataset": "golden_set_v1",
  "config": { "search_type": "hybrid", "alpha": 0.5 },
  "metrics": {
    "mrr_at_k": { "1": 0.45, "3": 0.58, "5": 0.63, "10": 0.68, "20": 0.71 },
    "ndcg_at_k": { "1": 0.42, "3": 0.55, "5": 0.61, "10": 0.67, "20": 0.70 },
    "recall_at_k": { "1": 0.35, "3": 0.55, "5": 0.68, "10": 0.85, "20": 0.92 },
    "precision_at_k": { "1": 0.35, "3": 0.18, "5": 0.14, "10": 0.085, "20": 0.046 },
    "latency_p50_ms": 120,
    "latency_p95_ms": 650,
    "latency_p99_ms": 1200,
    "total_queries": 100
  },
  "threshold_check": {
    "passed": true,
    "failures": []
  },
  "status": "completed",
  "created_at": "2024-01-15T10:00:00Z",
  "completed_at": "2024-01-15T10:05:00Z"
}
```

---

## Authentication

The MCP server uses the same API key authentication as the REST API.

### Configuration Options

| Environment Variable | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `CONTEXTFORGE_API_URL` | Yes | - | ContextForge API base URL |
| `CONTEXTFORGE_API_KEY` | Yes | - | API key for authentication |
| `CONTEXTFORGE_TIMEOUT` | No | 30 | Request timeout in seconds |

### API Key Management

Generate API keys via the ContextForge dashboard or CLI:
```bash
# Generate new key
contextforge api-key create --name "mcp-claude"

# List keys
contextforge api-key list

# Revoke key
contextforge api-key revoke <key-id>
```

---

## Transport Options

### stdio (Default - Claude Desktop)

Best for local development. The MCP server runs as a child process.

```json
{
  "mcpServers": {
    "contextforge": {
      "command": "uv",
      "args": ["run", "contextforge-mcp"],
      "env": { ... }
    }
  }
}
```

### SSE (Web/Remote)

For remote servers or web-based clients. Requires running MCP server as a service.

```bash
# Start MCP server with SSE
contextforge-mcp --transport sse --port 8001
```

Client configuration:
```json
{
  "mcpServers": {
    "contextforge": {
      "url": "http://localhost:8001/sse",
      "headers": {
        "Authorization": "Bearer your-api-key"
      }
    }
  }
}
```

---

## Tool Schema Reference

Each tool has a JSON Schema for validation. Schemas are available via MCP's `tools/list` capability.

### Ingest Document Schema
```json
{
  "type": "object",
  "properties": {
    "source_type": {
      "type": "string",
      "enum": ["text", "file", "url", "notion", "confluence", "github", "slack"]
    },
    "source_id": { "type": "string", "minLength": 1 },
    "content": { "type": "string" },
    "source_url": { "type": "string", "format": "uri" },
    "title": { "type": "string" },
    "strategy": { "type": "string", "enum": ["semantic", "hierarchical", "code", "fixed"] },
    "embedding_provider": { "type": "string", "enum": ["openai", "azure", "bedrock", "local"] },
    "embedding_model": { "type": "string" },
    "metadata": { "type": "object" },
    "chunk_size": { "type": "integer", "minimum": 100, "maximum": 2000 },
    "chunk_overlap": { "type": "integer", "minimum": 0, "maximum": 500 }
  },
  "required": ["source_type", "source_id"],
  "additionalProperties": false
}
```

### Query Knowledge Schema
```json
{
  "type": "object",
  "properties": {
    "query": { "type": "string", "minLength": 1 },
    "top_k": { "type": "integer", "minimum": 1, "maximum": 100, "default": 10 },
    "filters": {
      "type": "object",
      "properties": {
        "source_type": { "type": "string" },
        "tags": { "type": "array", "items": { "type": "string" } },
        "date_from": { "type": "string", "format": "date" },
        "date_to": { "type": "string", "format": "date" }
      }
    },
    "score_threshold": { "type": "number", "minimum": 0, "maximum": 1 },
    "search_type": { "type": "string", "enum": ["hybrid", "vector", "keyword"], "default": "hybrid" },
    "alpha": { "type": "number", "minimum": 0, "maximum": 1, "default": 0.5 }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

---

## Development

### Running Locally

```bash
# Install in development mode
cd contextforge
uv pip install -e ".[mcp]"

# Run MCP server
uv run contextforge-mcp

# Run with SSE transport
uv run contextforge-mcp --transport sse --port 8001

# Debug mode (verbose logging)
LOG_LEVEL=DEBUG uv run contextforge-mcp
```

### Project Structure

```
src/contextforge/mcp/
├── __init__.py
├── server.py           # Main MCP server entry point
├── tools/
│   ├── __init__.py
│   ├── ingestion.py    # ingest_document tool
│   ├── query.py        # query_knowledge tool
│   ├── documents.py    # list_documents tool
│   └── evaluation.py   # eval tools
├── transport/
│   ├── __init__.py
│   ├── stdio.py        # stdio transport
│   └── sse.py          # SSE transport
├── auth.py             # API key validation
├── config.py           # MCP server config
└── schemas.py          # JSON Schema definitions
```

### Adding New Tools

1. Create tool module in `tools/`
2. Define schema in `schemas.py`
3. Register in `server.py`:

```python
from contextforge.mcp.tools.my_tool import MyTool

server.add_tool(MyTool())
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "Connection refused" | API not running | Start ContextForge API: `make run` |
| "Invalid API key" | Wrong/missing key | Check `CONTEXTFORGE_API_KEY` in config |
| "Tool not found" | MCP server outdated | Update: `uv pip install --upgrade contextforge-mcp` |
| "Timeout" | Slow query | Increase `CONTEXTFORGE_TIMEOUT` |
| No tools in Claude | Config syntax error | Validate JSON, restart Claude Desktop |

### Debug Logging

Enable debug logging to see MCP protocol messages:

```bash
# stdio transport
LOG_LEVEL=DEBUG uv run contextforge-mcp 2>&1 | head -50

# Check Claude Desktop logs
# macOS: ~/Library/Logs/Claude/
# Windows: %APPDATA%\Claude\logs\
```

### Testing Tools Manually

Use the MCP inspector (when available) or test via CLI:

```bash
# Test ingest
echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "ingest_document", "arguments": {"source_type": "text", "source_id": "test", "content": "Hello world"}}}' | uv run contextforge-mcp
```

---

## Security Considerations

1. **API Key Storage**: Store in OS keychain/credential manager, not plain text
2. **Network**: Use HTTPS for remote MCP servers
3. **Rate Limiting**: MCP calls count against API rate limits
4. **Data Access**: Tools respect document-level permissions (future)
5. **Audit**: All MCP tool calls logged with request ID

---

## Roadmap

- [ ] **Resources**: Expose documents as MCP resources for reading
- [ ] **Prompts**: Pre-built prompts for common RAG workflows
- [ ] **Streaming**: Server-sent events for long-running operations
- [ ] **OAuth**: OAuth2/OIDC authentication flow
- [ ] **Multi-tenancy**: Namespace isolation per user/team
- [ ] **Tool Composition**: Chained tools (ingest → query → eval)

---

## References

- [MCP Specification](https://modelcontextprotocol.io/specification)
- [Claude Desktop MCP Setup](https://claude.ai/docs/mcp)
- [Cursor MCP Integration](https://cursor.sh/docs/mcp)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
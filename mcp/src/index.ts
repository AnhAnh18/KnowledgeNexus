#!/usr/bin/env node
/**
 * KnowledgeNexus MCP Server
 *
 * MCP server that bridges Cline with the KnowledgeNexus RAG platform.
 * Provides tools to search knowledge and export results to Markdown files.
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import express, { type Request, type Response } from 'express';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';
import axios from 'axios';
import * as fs from 'fs';
import * as path from 'path';


// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const API_BASE_URL = process.env.KNOWLEDGENEXUS_API_URL || 'http://localhost:8000';
const MCP_TRANSPORT = (process.env.MCP_TRANSPORT || 'stdio').toLowerCase();
const MCP_HTTP_HOST = process.env.MCP_HTTP_HOST || '0.0.0.0';

// Validate port: must be 1-65535
const portStr = process.env.MCP_HTTP_PORT || '8787';
const portNum = parseInt(portStr, 10);
if (isNaN(portNum) || portNum < 1 || portNum > 65535) {
  console.error(`[Error] Invalid MCP_HTTP_PORT: "${portStr}" (must be 1-65535)`);
  process.exit(1);
}
const MCP_HTTP_PORT = portNum;

// ---------------------------------------------------------------------------
// Types (matching KnowledgeNexus REST API schemas)
// ---------------------------------------------------------------------------

interface Citation {
  chunk_id: string;
  document_id: string;
  title: string;
  url: string | null;
  source_type: string;
  source_id: string;
  chunk_index: number;
  total_chunks: number;
  page_id: string | null;
  space_key: string | null;
  repo: string | null;
  branch: string | null;
  file_path: string | null;
  symbol: string | null;
  line_start: number | null;
  line_end: number | null;
  heading_path: string | null;
  content_kind: string | null;
  language: string | null;
  source_version: string | null;
}

interface RetrievedChunk {
  content: string;
  score: number;
  citation: Citation;
}

interface RetrieveResponse {
  query: string;
  total: number;
  results: RetrievedChunk[];
}

interface DocumentItem {
  id: string;
  title: string;
  source_type: string;
  source_id: string;
  url: string | null;
  created_at: string;
  updated_at: string;
}

interface ListDocumentsResponse {
  documents: DocumentItem[];
  total: number;
  limit: number;
  offset: number;
}

// ---------------------------------------------------------------------------
// API Helpers
// ---------------------------------------------------------------------------

async function searchKnowledge(
  query: string,
  topK: number = 5,
  scoreThreshold: number = 0.0,
  filters: Record<string, unknown> = {}
): Promise<RetrieveResponse> {
  const response = await axios.post<RetrieveResponse>(
    `${API_BASE_URL}/api/v1/retrieve`,
    {
      query,
      top_k: topK,
      score_threshold: scoreThreshold,
      filters,
    },
    {
      headers: { 'Content-Type': 'application/json' },
      timeout: 30000,
    }
  );
  return response.data;
}

async function listDocuments(
  limit: number = 100,
  offset: number = 0
): Promise<ListDocumentsResponse> {
  const response = await axios.get<ListDocumentsResponse>(
    `${API_BASE_URL}/api/v1/documents`,
    {
      params: { limit, offset },
      timeout: 30000,
    }
  );
  return response.data;
}

async function getStoreStats(): Promise<Record<string, unknown>> {
  const response = await axios.get(`${API_BASE_URL}/api/v1/store/stats`, {
    timeout: 30000,
  });
  return response.data as Record<string, unknown>;
}

async function healthCheck(): Promise<Record<string, unknown>> {
  const response = await axios.get(`${API_BASE_URL}/api/v1/health`, {
    timeout: 10000,
  });
  return response.data as Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Markdown Export Helper
// ---------------------------------------------------------------------------

function formatResultsAsMarkdown(query: string, results: RetrieveResponse): string {
  const lines: string[] = [];

  lines.push(`# Search Results: "${query}"`);
  lines.push('');
  lines.push(`> **Query:** ${query}  `);
  lines.push(`> **Total results:** ${results.total}  `);
  lines.push(`> **Generated:** ${new Date().toISOString()}`);
  lines.push('');
  lines.push('---');
  lines.push('');

  if (results.results.length === 0) {
    lines.push('No results found.');
    return lines.join('\n');
  }

  results.results.forEach((chunk, idx) => {
    const c = chunk.citation;
    lines.push(`## Result ${idx + 1} (score: ${chunk.score.toFixed(4)})`);
    lines.push('');

    // Citation metadata
    lines.push('| Field | Value |');
    lines.push('|-------|-------|');
    lines.push(`| **Title** | ${c.title} |`);
    lines.push(`| **Source Type** | ${c.source_type} |`);
    lines.push(`| **Source ID** | ${c.source_id} |`);
    lines.push(`| **Document ID** | ${c.document_id} |`);
    lines.push(`| **Chunk** | ${c.chunk_index + 1} / ${c.total_chunks} |`);
    if (c.url) lines.push(`| **URL** | ${c.url} |`);
    if (c.repo) lines.push(`| **Repo** | ${c.repo} |`);
    if (c.branch) lines.push(`| **Branch** | ${c.branch} |`);
    if (c.file_path) lines.push(`| **File Path** | ${c.file_path} |`);
    if (c.symbol) lines.push(`| **Symbol** | ${c.symbol} |`);
    if (c.line_start !== null && c.line_end !== null) {
      lines.push(`| **Lines** | ${c.line_start}-${c.line_end} |`);
    }
    if (c.heading_path) lines.push(`| **Heading Path** | ${c.heading_path} |`);
    if (c.content_kind) lines.push(`| **Content Kind** | ${c.content_kind} |`);
    if (c.language) lines.push(`| **Language** | ${c.language} |`);
    if (c.page_id) lines.push(`| **Page ID** | ${c.page_id} |`);
    if (c.space_key) lines.push(`| **Space Key** | ${c.space_key} |`);
    if (c.source_version) lines.push(`| **Source Version** | ${c.source_version} |`);
    lines.push('');

    // Content
    lines.push('### Content');
    lines.push('');
    lines.push('```');
    lines.push(chunk.content);
    lines.push('```');
    lines.push('');
    lines.push('---');
    lines.push('');
  });

  return lines.join('\n');
}

function formatDocumentsAsMarkdown(
  query: string,
  docs: ListDocumentsResponse
): string {
  const lines: string[] = [];

  lines.push(`# Documents List`);
  lines.push('');
  lines.push(`> **Total:** ${docs.total}  `);
  lines.push(`> **Limit:** ${docs.limit}  `);
  lines.push(`> **Offset:** ${docs.offset}  `);
  lines.push(`> **Generated:** ${new Date().toISOString()}`);
  lines.push('');
  lines.push('---');
  lines.push('');

  if (docs.documents.length === 0) {
    lines.push('No documents found.');
    return lines.join('\n');
  }

  lines.push('| # | Title | Source Type | Source ID | URL | Created | Updated |');
  lines.push('|---|-------|-------------|-----------|-----|---------|---------|');
  docs.documents.forEach((doc, idx) => {
    lines.push(
      `| ${idx + 1} | ${doc.title} | ${doc.source_type} | ${doc.source_id} | ${doc.url || '-'} | ${doc.created_at} | ${doc.updated_at} |`
    );
  });
  lines.push('');

  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------

function createMcpServer(): Server {
  const server = new Server(
    {
      name: 'knowledgenexus-mcp',
      version: '0.1.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  registerToolHandlers(server);

  server.onerror = (error) =>
    console.error('[KnowledgeNexus MCP Error]', error);

  return server;
}

function registerToolHandlers(server: Server): void {
  // List available tools
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [
        {
          name: 'search',
          description:
            'Search the KnowledgeNexus RAG platform for relevant knowledge chunks. ' +
            'Returns ranked results with content, scores, and citation metadata. ' +
            'IMPORTANT: When you use this data to answer the user, you MUST cite the ' +
            'source (title + URL or file path, shown per result) for every fact you use.',
          inputSchema: {
            type: 'object',
            properties: {
              query: {
                type: 'string',
                description: 'The search query text',
              },
              top_k: {
                type: 'number',
                description: 'Number of results to return (1-50, default: 5)',
                minimum: 1,
                maximum: 50,
              },
              score_threshold: {
                type: 'number',
                description: 'Minimum similarity score threshold (0.0-1.0, default: 0.0)',
                minimum: 0.0,
                maximum: 1.0,
              },
            },
            required: ['query'],
          },
        },
        {
          name: 'export_search_results',
          description:
            'Search KnowledgeNexus and export the results to a Markdown (.md) file. ' +
            'The file will contain formatted search results with citations and content.',
          inputSchema: {
            type: 'object',
            properties: {
              query: {
                type: 'string',
                description: 'The search query text',
              },
              output_path: {
                type: 'string',
                description:
                  'Absolute or relative path for the output .md file ' +
                  '(e.g. "C:/Users/phong.dv/Documents/search-results.md")',
              },
              top_k: {
                type: 'number',
                description: 'Number of results to return (1-50, default: 5)',
                minimum: 1,
                maximum: 50,
              },
              score_threshold: {
                type: 'number',
                description: 'Minimum similarity score threshold (0.0-1.0, default: 0.0)',
                minimum: 0.0,
                maximum: 1.0,
              },
            },
            required: ['query', 'output_path'],
          },
        },
        {
          name: 'list_documents',
          description:
            'List all documents stored in the KnowledgeNexus platform with pagination support.',
          inputSchema: {
            type: 'object',
            properties: {
              limit: {
                type: 'number',
                description: 'Maximum number of documents to return (1-1000, default: 100)',
                minimum: 1,
                maximum: 1000,
              },
              offset: {
                type: 'number',
                description: 'Number of documents to skip (default: 0)',
                minimum: 0,
              },
            },
          },
        },
        {
          name: 'export_documents_list',
          description:
            'List all documents in KnowledgeNexus and export them to a Markdown (.md) file.',
          inputSchema: {
            type: 'object',
            properties: {
              output_path: {
                type: 'string',
                description:
                  'Absolute or relative path for the output .md file',
              },
              limit: {
                type: 'number',
                description: 'Maximum number of documents to return (1-1000, default: 100)',
                minimum: 1,
                maximum: 1000,
              },
              offset: {
                type: 'number',
                description: 'Number of documents to skip (default: 0)',
                minimum: 0,
              },
            },
            required: ['output_path'],
          },
        },
        {
          name: 'get_store_stats',
          description:
            'Get storage statistics from KnowledgeNexus (Qdrant vector DB + SQLite metadata).',
          inputSchema: {
            type: 'object',
            properties: {},
          },
        },
        {
          name: 'health_check',
          description:
            'Check the health status of the KnowledgeNexus platform (SQLite + Qdrant connectivity).',
          inputSchema: {
            type: 'object',
            properties: {},
          },
        },
      ],
    }));

  // Handle tool calls
  server.setRequestHandler(
    CallToolRequestSchema,
      async (request) => {
        const { name, arguments: args } = request.params;

        try {
          switch (name) {
            // -----------------------------------------------------------------
            // search
            // -----------------------------------------------------------------
            case 'search': {
              if (!args || typeof args.query !== 'string') {
                throw new McpError(
                  ErrorCode.InvalidParams,
                  'query (string) is required'
                );
              }
              const query = args.query as string;
              const topK = (args.top_k as number) ?? 5;
              const scoreThreshold = (args.score_threshold as number) ?? 0.0;

              const result = await searchKnowledge(query, topK, scoreThreshold);

              // Format as readable text
              const summary =
                `Found ${result.total} result(s) for "${query}".\n` +
                `Reminder: cite the Title and URL/File shown below for every fact you use in your answer.\n\n` +
                result.results
                  .map((chunk, idx) => {
                    const c = chunk.citation;
                    return (
                      `--- Result ${idx + 1} (score: ${chunk.score.toFixed(4)}) ---\n` +
                      `Title: ${c.title}\n` +
                      `Source: ${c.source_type} / ${c.source_id}\n` +
                      (c.file_path ? `File: ${c.file_path}` +
                        (c.line_start !== null ? `:${c.line_start}-${c.line_end}` : '') + '\n' : '') +
                      (c.url ? `URL: ${c.url}\n` : '') +
                      `\nContent:\n${chunk.content}\n`
                    );
                  })
                  .join('\n');

              return {
                content: [{ type: 'text', text: summary }],
              };
            }

            // -----------------------------------------------------------------
            // export_search_results
            // -----------------------------------------------------------------
            case 'export_search_results': {
              if (!args || typeof args.query !== 'string') {
                throw new McpError(
                  ErrorCode.InvalidParams,
                  'query (string) is required'
                );
              }
              if (typeof args.output_path !== 'string') {
                throw new McpError(
                  ErrorCode.InvalidParams,
                  'output_path (string) is required'
                );
              }

              const query = args.query as string;
              const outputPath = args.output_path as string;
              const topK = (args.top_k as number) ?? 5;
              const scoreThreshold = (args.score_threshold as number) ?? 0.0;

              const result = await searchKnowledge(query, topK, scoreThreshold);
              const markdown = formatResultsAsMarkdown(query, result);

              // Ensure directory exists
              const dir = path.dirname(outputPath);
              if (dir && !fs.existsSync(dir)) {
                fs.mkdirSync(dir, { recursive: true });
              }
              fs.writeFileSync(outputPath, markdown, 'utf-8');

              return {
                content: [
                  {
                    type: 'text',
                    text:
                      `Search results exported to: ${outputPath}\n` +
                      `Query: "${query}"\n` +
                      `Results: ${result.total}\n` +
                        `File size: ${fs.statSync(outputPath).size} bytes`,
                  },
                ],
              };
            }

            // -----------------------------------------------------------------
            // list_documents
            // -----------------------------------------------------------------
            case 'list_documents': {
              const limit = (args?.limit as number) ?? 100;
              const offset = (args?.offset as number) ?? 0;

              const result = await listDocuments(limit, offset);

              const summary =
                `Documents: ${result.total} total (showing ${result.documents.length}, offset ${result.offset})\n\n` +
                result.documents
                  .map((doc, idx) => {
                    return (
                      `${idx + 1}. ${doc.title}\n` +
                      `   ID: ${doc.id}\n` +
                      `   Source: ${doc.source_type} / ${doc.source_id}\n` +
                      (doc.url ? `   URL: ${doc.url}\n` : '') +
                      `   Created: ${doc.created_at}\n`
                    );
                  })
                  .join('\n');

              return {
                content: [{ type: 'text', text: summary }],
              };
            }

            // -----------------------------------------------------------------
            // export_documents_list
            // -----------------------------------------------------------------
            case 'export_documents_list': {
              if (!args || typeof args.output_path !== 'string') {
                throw new McpError(
                  ErrorCode.InvalidParams,
                  'output_path (string) is required'
                );
              }

              const outputPath = args.output_path as string;
              const limit = (args.limit as number) ?? 100;
              const offset = (args.offset as number) ?? 0;

              const result = await listDocuments(limit, offset);
              const markdown = formatDocumentsAsMarkdown('', result);

              const dir = path.dirname(outputPath);
              if (dir && !fs.existsSync(dir)) {
                fs.mkdirSync(dir, { recursive: true });
              }
              fs.writeFileSync(outputPath, markdown, 'utf-8');

              return {
                content: [
                  {
                    type: 'text',
                    text:
                      `Documents list exported to: ${outputPath}\n` +
                      `Total: ${result.total}\n` +
                      `File size: ${fs.statSync(outputPath).size} bytes`,
                  },
                ],
              };
            }

            // -----------------------------------------------------------------
            // get_store_stats
            // -----------------------------------------------------------------
            case 'get_store_stats': {
              const stats = await getStoreStats();
              return {
                content: [
                  { type: 'text', text: JSON.stringify(stats, null, 2) },
                ],
              };
            }

            // -----------------------------------------------------------------
            // health_check
            // -----------------------------------------------------------------
            case 'health_check': {
              const health = await healthCheck();
              return {
                content: [
                  { type: 'text', text: JSON.stringify(health, null, 2) },
                ],
              };
            }

            // -----------------------------------------------------------------
            default:
              throw new McpError(
                ErrorCode.MethodNotFound,
                `Unknown tool: ${name}`
              );
          }
        } catch (error) {
          if (axios.isAxiosError(error)) {
            const detail =
              error.response?.data?.detail ||
              error.response?.data?.message ||
              error.message;
            return {
              content: [
                {
                  type: 'text',
                  text: `KnowledgeNexus API error: ${detail}`,
                },
              ],
              isError: true,
            };
          }
          throw error;
        }
      }
    );
}

// ---------------------------------------------------------------------------
// Transports
// ---------------------------------------------------------------------------

async function runStdio(): Promise<void> {
  const server = createMcpServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);

  process.on('SIGINT', async () => {
    await server.close();
    process.exit(0);
  });

  console.error('KnowledgeNexus MCP server running on stdio');
  console.error(`API base URL: ${API_BASE_URL}`);
}


// ---------------------------------------------------------------------------
// Multi-session HTTP Transport
// ---------------------------------------------------------------------------

// Map of session ID → transport, so each MCP client gets its own session.
// This allows multiple clients (Cline, Gemini, Claude, etc.) to connect simultaneously.
const sessionTransports = new Map<string, StreamableHTTPServerTransport>();

async function runHttp(): Promise<void> {
  // IMPORTANT: Do NOT use createMcpExpressApp() — it registers express.json() globally,
  // which consumes the request body stream. When @hono/node-server (used internally by
  // StreamableHTTPServerTransport) tries to convert the Node.js request to a Web Standard
  // Request, it fails because the stream is already consumed, resulting in HTTP 500.
  //
  // Instead, create a plain Express app WITHOUT express.json() and let the SDK read
  // the body from the raw stream itself via @hono/node-server's conversion.
  const app = express();

  // Accept header middleware for MCP compatibility.
  // Some MCP clients (e.g. older Cline builds) don't send Accept: application/json, text/event-stream
  // which causes "Not Acceptable" errors. Inject it if missing.
  // NOTE: @hono/node-server (used internally by StreamableHTTPServerTransport) reads headers from
  // req.rawHeaders (flat array), NOT req.headers (object). We must patch BOTH.
  app.use('/mcp', (req: Request, res: Response, next) => {
    // CORS headers for remote access
    res.header('Access-Control-Allow-Origin', '*');
    res.header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
    res.header('Access-Control-Allow-Headers', 'Content-Type, Accept, mcp-session-id');
    res.header('Connection', 'keep-alive');
    res.header('Keep-Alive', 'timeout=90, max=100');

    // Handle preflight requests
    if (req.method === 'OPTIONS') {
      res.status(200).end();
      return;
    }

    const accept = req.headers['accept'] as string | undefined;
    const required = ['application/json', 'text/event-stream'];
    if (!accept || !required.every((t) => accept.includes(t))) {
      const newAccept = 'application/json, text/event-stream';
      req.headers['accept'] = newAccept;
      const raw = req.rawHeaders as string[];
      let found = false;
      for (let i = 0; i < raw.length; i += 2) {
        if (raw[i].toLowerCase() === 'accept') {
          raw[i + 1] = newAccept;
          found = true;
          break;
        }
      }
      if (!found) {
        raw.push('Accept', newAccept);
      }
    }
    next();
  });

  // POST: handle MCP JSON-RPC requests (initialize, tools/list, tools/call, etc.)
  //
  // Multi-session handling:
  // - If the request has an mcp-session-id header, route it to the existing transport.
  // - If it's an initialize request (no session ID), create a new transport + server.
  // - This allows multiple MCP clients to connect simultaneously.
  app.post('/mcp', async (req: Request, res: Response) => {
    try {
      const sessionId = req.headers['mcp-session-id'] as string | undefined;

      if (sessionId && sessionTransports.has(sessionId)) {
        // Existing session — route to the transport that owns this session
        const transport = sessionTransports.get(sessionId)!;
        await transport.handleRequest(req, res);
      } else if (sessionId && !sessionTransports.has(sessionId)) {
        // Session ID provided but not found — server was likely restarted.
        // Tell the client to re-initialize.
        res.status(404).json({
          jsonrpc: '2.0',
          error: {
            code: -32001,
            message: 'Session not found. The server may have been restarted. Please re-initialize.',
          },
          id: null,
        });
      } else {
        // No session ID — this should be an initialize request.
        // Create a fresh transport + server for this new client.
        const transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => crypto.randomUUID(),
          onsessioninitialized: (newSessionId: string) => {
            sessionTransports.set(newSessionId, transport);
          },
          onsessionclosed: (closedSessionId: string) => {
            sessionTransports.delete(closedSessionId);
          },
        });
        const server = createMcpServer();
        await server.connect(transport);
        await transport.handleRequest(req, res);
      }
    } catch (error) {
      console.error('[KnowledgeNexus MCP HTTP POST Error]', error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: '2.0',
          error: { code: -32603, message: 'Internal server error', data: String(error) },
          id: null,
        });
      }
    }
  });

  // GET: handle SSE streaming connections (server-to-client notifications)
  app.get('/mcp', async (req: Request, res: Response) => {
    try {
      const sessionId = req.headers['mcp-session-id'] as string | undefined;
      if (sessionId && sessionTransports.has(sessionId)) {
        const transport = sessionTransports.get(sessionId)!;
        await transport.handleRequest(req, res);
      } else {
        res.status(400).json({
          jsonrpc: '2.0',
          error: { code: -32000, message: 'Bad Request: No valid session. Send an initialize request first.' },
          id: null,
        });
      }
    } catch (error) {
      console.error('[KnowledgeNexus MCP HTTP GET Error]', error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: '2.0',
          error: { code: -32603, message: 'Internal server error' },
          id: null,
        });
      }
    }
  });

  // DELETE: handle session cleanup/termination
  app.delete('/mcp', async (req: Request, res: Response) => {
    try {
      const sessionId = req.headers['mcp-session-id'] as string | undefined;
      if (sessionId && sessionTransports.has(sessionId)) {
        const transport = sessionTransports.get(sessionId)!;
        await transport.handleRequest(req, res);
        sessionTransports.delete(sessionId);
      } else {
        res.status(400).json({
          jsonrpc: '2.0',
          error: { code: -32000, message: 'Bad Request: No valid session to delete.' },
          id: null,
        });
      }
    } catch (error) {
      console.error('[KnowledgeNexus MCP HTTP DELETE Error]', error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: '2.0',
          error: { code: -32603, message: 'Internal server error' },
          id: null,
        });
      }
    }
  });

  // Global error handler — logs any uncaught errors from middleware/routes
  app.use((err: Error, req: Request, res: Response, next: (err?: unknown) => void) => {
    console.error('[KnowledgeNexus MCP Express Error]', err);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: '2.0',
        error: { code: -32603, message: 'Internal server error', data: String(err) },
        id: null,
      });
    }
  });

  const httpServer = app.listen(MCP_HTTP_PORT, MCP_HTTP_HOST);

  // Configure socket timeouts for stable long-running connections
  httpServer.keepAliveTimeout = 90000; // 90 seconds
  httpServer.headersTimeout = 95000; // 95 seconds (must be > keepAliveTimeout)
  httpServer.requestTimeout = 120000; // 120 seconds for individual requests

  httpServer.on('listening', () => {
    console.error(
      `KnowledgeNexus MCP server running on http://${MCP_HTTP_HOST}:${MCP_HTTP_PORT}/mcp`
    );
    console.error(`API base URL: ${API_BASE_URL}`);
    console.error(`Connection settings: keepAliveTimeout=90s, requestTimeout=120s`);
  });

  httpServer.on('error', (error) => {
    console.error(`[KnowledgeNexus MCP HTTP Server Error] ${error.message}`);
    process.exit(1);
  });
}


// ---------------------------------------------------------------------------
// Process-level error handlers — prevent server crash on unhandled errors
// ---------------------------------------------------------------------------

process.on('uncaughtException', (error) => {
  console.error('[KnowledgeNexus MCP Uncaught Exception]', error);
  // Do NOT exit — keep the server running
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('[KnowledgeNexus MCP Unhandled Rejection]', reason);
  // Do NOT exit — keep the server running
});

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

if (MCP_TRANSPORT === 'http') {
  runHttp().catch(console.error);
} else {
  runStdio().catch(console.error);
}

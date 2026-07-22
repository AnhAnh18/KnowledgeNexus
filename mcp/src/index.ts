#!/usr/bin/env node
/**
 * KnowledgeNexus MCP Server
 *
 * MCP server that bridges Cline with the KnowledgeNexus RAG platform.
 * Provides tools to search knowledge and export results to Markdown files.
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
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

class KnowledgeNexusServer {
  private server: Server;

  constructor() {
    this.server = new Server(
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

    this.setupToolHandlers();

    this.server.onerror = (error) =>
      console.error('[KnowledgeNexus MCP Error]', error);

    process.on('SIGINT', async () => {
      await this.server.close();
      process.exit(0);
    });
  }

  private setupToolHandlers(): void {
    // List available tools
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [
        {
          name: 'search',
          description:
            'Search the KnowledgeNexus RAG platform for relevant knowledge chunks. ' +
            'Returns ranked results with content, scores, and citation metadata.',
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
    this.server.setRequestHandler(
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
                `Found ${result.total} result(s) for "${query}".\n\n` +
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

  async run(): Promise<void> {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error('KnowledgeNexus MCP server running on stdio');
    console.error(`API base URL: ${API_BASE_URL}`);
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const server = new KnowledgeNexusServer();
server.run().catch(console.error);

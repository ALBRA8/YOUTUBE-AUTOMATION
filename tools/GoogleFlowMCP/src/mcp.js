#!/usr/bin/env node
// srz-google-flow-mcp: MCP server (stdio) for Google Flow image generation. Calls are
// serialized in-process and across processes (src/lock.js): Flow's UI handles one action at a time.
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { generateImages, newProject, uploadFile, listAssets, ASPECTS, DEFAULT_OUT } from './flow.js';
import { withFlowLock } from './lock.js';

const server = new McpServer({ name: 'srz-google-flow-mcp', version: '1.0.1' });

let queue = Promise.resolve();
const serial = (fn) => (queue = queue.then(() => withFlowLock(fn), () => withFlowLock(fn)));
const text = (t) => ({ content: [{ type: 'text', text: t }] });
const fail = (what, err) => ({ isError: true, content: [{ type: 'text', text: `${what} failed: ${err.message}` }] });

server.registerTool('flow_upload_file', {
  description: 'Upload a local image file into the Google Flow project and give it a name, so prompts can reference it as @{name}. '
    + 'Name it by its role (e.g. "avatar", "product", "logo"). If an asset with that name already exists it is reused (no upload) unless replace=true. '
    + 'Typical flow: upload the reference images first, then call flow_generate_image with a prompt that contains @{name}.',
  inputSchema: {
    filePath: z.string().describe('Absolute path of the local image to upload'),
    name: z.string().optional().describe('Asset name to use in prompts as @{name}. Defaults to the file name without extension'),
    replace: z.boolean().default(false).describe('Upload again even if an asset with this name exists'),
  },
}, async ({ filePath, name, replace }) => {
  try {
    const r = await serial(() => uploadFile({ filePath, name, replace }));
    return text(r.reused
      ? `An asset named "${r.name}" already exists in the project; reusing it. Reference it as @{${r.name}}.`
      : `Uploaded and named "${r.name}". Reference it in prompts as @{${r.name}}.`);
  } catch (err) { return fail('Upload', err); }
});

server.registerTool('flow_list_assets', {
  description: 'List the names of the images in the current Google Flow project (uploaded files and generations). Any of them can be referenced in a prompt as @{name}.',
  inputSchema: {},
}, async () => {
  try {
    const assets = await serial(() => listAssets());
    return text(assets.length ? assets.map((a) => `- ${a.name}`).join('\n') : 'The project has no images yet.');
  } catch (err) { return fail('Listing assets', err); }
});

server.registerTool('flow_generate_image', {
  description: 'Generate images with Google Flow (Nano Banana) in the user\'s signed-in Chrome and save them to disk; returns the local file paths. Images do not consume Flow credits. '
    + 'To use reference images, upload them first with flow_upload_file and write @{name} in the prompt where the image should be attached: '
    + 'each @{name} becomes a reference chip to that asset (e.g. "Image 1 -> Avatar: @{avatar}"). Any other "@" (like "@Image 1") stays as plain text. '
    + 'Multi-line prompts are kept as written.',
  inputSchema: {
    prompt: z.string().min(1).describe('What to generate. Use @{name} to reference uploaded assets'),
    aspect: z.enum(ASPECTS).default('1:1'),
    count: z.number().int().min(1).max(4).default(1),
    model: z.enum(['pro', '2', 'lite']).default('2').describe('pro = Nano Banana Pro, 2 = Nano Banana 2, lite = Nano Banana 2 Lite'),
    outDir: z.string().optional().describe(`Folder to save into (default ${DEFAULT_OUT})`),
  },
}, async ({ prompt, aspect, count, model, outDir }) => {
  try {
    const r = await serial(() => generateImages({ prompt, aspect, count, model, outDir: outDir || DEFAULT_OUT }));
    return text(`Generated ${r.files.length} image(s) in ${r.seconds}s with ${r.model} (${r.aspect}):\n${r.files.join('\n')}`);
  } catch (err) { return fail('Flow generation', err); }
});

server.registerTool('flow_new_project', {
  description: 'Create a fresh Google Flow project and use it from now on. Assets uploaded to the previous project are not available in the new one.',
  inputSchema: {},
}, async () => {
  try {
    const id = await serial(() => newProject());
    return text(`Now working in Flow project ${id}`);
  } catch (err) { return fail('Creating a project', err); }
});

await server.connect(new StdioServerTransport());

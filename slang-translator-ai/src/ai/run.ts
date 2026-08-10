/**
 * The one place that calls a forced tool and pulls out its input.
 *
 * Structured output here means forcing `tool_choice` at a single schema-bound
 * tool, not `output_config.format` — the installed SDK (0.40.1) predates that
 * parameter. Forced tool use is the reliable structured-output mechanism for
 * this SDK version and is what every ai/* call goes through.
 */

import type Anthropic from '@anthropic-ai/sdk';
import { AiError } from './errors.js';

export async function callTool(
  client: Anthropic,
  params: Anthropic.MessageCreateParamsNonStreaming,
  toolName: string,
): Promise<Record<string, unknown>> {
  const response = await client.messages.create(params);

  if (response.stop_reason !== 'tool_use') {
    throw new AiError(`${toolName}: unexpected stop_reason ${response.stop_reason ?? 'null'}`);
  }

  const block = response.content.find(
    (b): b is Anthropic.ToolUseBlock => b.type === 'tool_use' && b.name === toolName,
  );
  if (block === undefined) {
    throw new AiError(`${toolName}: no matching tool_use block in response`);
  }
  if (typeof block.input !== 'object' || block.input === null) {
    throw new AiError(`${toolName}: tool input was not an object`);
  }
  return block.input as Record<string, unknown>;
}

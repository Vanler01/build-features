/**
 * The one place that calls a forced tool and pulls out its input.
 *
 * Structured output here means forcing `tool_choice` at a single schema-bound
 * tool, not `output_config.format` — the installed SDK (0.40.1) predates that
 * parameter. Forced tool use is the reliable structured-output mechanism for
 * this SDK version and is what every ai/* call goes through.
 */

import type Anthropic from '@anthropic-ai/sdk';
import type { CallLog } from '../store/spend.js';
import { AiError } from './errors.js';

/**
 * `purpose` and `log` exist for cost accounting, and this is the only place
 * they need to be wired: every Claude call in the project goes through here,
 * so counting here cannot drift the way three separate call sites would.
 *
 * The call is recorded *before* the response is inspected, because a call that
 * came back malformed still cost money — counting only successes would
 * undercount exactly when something is going wrong in a loop.
 */
export async function callTool(
  client: Anthropic,
  params: Anthropic.MessageCreateParamsNonStreaming,
  toolName: string,
  purpose: string,
  log?: CallLog,
): Promise<Record<string, unknown>> {
  const response = await client.messages.create(params);
  log?.record(params.model, purpose);

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

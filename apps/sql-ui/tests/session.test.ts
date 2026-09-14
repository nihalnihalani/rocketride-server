// MIT License
//
// Copyright (c) 2026 Aparavi Software AG
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

// =============================================================================
// CONNECT SESSION — unit tests for the tool-support classifier
// =============================================================================
//
// `isUnsupportedToolError` decides whether refreshSchema falls back to
// get_schema. It is deliberately asymmetric: only errors that clearly came
// from a tool that RAN are classified as real failures.
// =============================================================================

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { isUnsupportedToolError } from '../src/connect/session';

describe('isUnsupportedToolError', () => {
	it('recognises the engine chain reporting that no node owns the tool', () => {
		assert.equal(isUnsupportedToolError(new Error('tool.invoke: refresh_schema not owned')), true);
		assert.equal(isUnsupportedToolError(new Error('Unknown dynamic tool: refresh_schema')), true);
		assert.equal(isUnsupportedToolError(new Error('no tool methods')), true);
	});

	it('matches case-insensitively', () => {
		assert.equal(isUnsupportedToolError(new Error('TOOL.INVOKE: REFRESH_SCHEMA NOT OWNED')), true);
	});

	it('refuses to swallow an error from a tool that actually ran', () => {
		assert.equal(isUnsupportedToolError(new Error('SQL execution failed: Error 1146: no such table')), false);
		assert.equal(isUnsupportedToolError(new Error('EXECUTE query exceeded max_execute_rows=25000')), false);
		assert.equal(isUnsupportedToolError(new Error('execute tool is disabled for this node (set allow_execute=true)')), false);
		assert.equal(isUnsupportedToolError(new Error('unknown or expired transaction session: abc')), false);
	});

	it('treats an unclassifiable failure as unsupported so the caller degrades', () => {
		assert.equal(isUnsupportedToolError(new Error('socket hang up')), true);
		assert.equal(isUnsupportedToolError('plain string rejection'), true);
		assert.equal(isUnsupportedToolError(undefined), true);
	});
});

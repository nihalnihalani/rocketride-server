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
// SQL QUOTE — unit tests for the app's only literal quoter
// =============================================================================

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { quoteLiteral } from '../src/sql/quote';

describe('quoteLiteral', () => {
	it('wraps an ordinary value in single quotes', () => {
		assert.equal(quoteLiteral('orders'), "'orders'");
	});

	it('quotes a numeric-looking value instead of passing it through bare', () => {
		// The regression this module exists for: an unquoted all-digit value
		// compared against a text catalog column is a number comparison.
		assert.equal(quoteLiteral('2026'), "'2026'");
		assert.equal(quoteLiteral('-1.5'), "'-1.5'");
	});

	it('doubles every embedded single quote', () => {
		assert.equal(quoteLiteral("o'brien"), "'o''brien'");
		assert.equal(quoteLiteral("''"), "''''''");
	});

	it('quotes the empty string', () => {
		assert.equal(quoteLiteral(''), "''");
	});
});

#!/usr/bin/env node
// Reduce the natural template-before-fraction captures to checked editor
// transition oracles. Raw RAM, screenshots, and the trace remain external.

'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const root = path.dirname(__dirname);
const rom = require(path.join(root,'web','mathprint','rom-engine.js'));
const font = JSON.parse(fs.readFileSync(
  path.join(root,'web','mathprint','font.json')));
const capture = require('./capture-mathprint-editor-navigation.js');
rom.setSettledTokenStrings(JSON.parse(fs.readFileSync(
  path.join(root,'web','mathprint','token-strings.json'))));

const CASES = [
  ['radical',[0xbc]],
  ['nthroot',[0xf1]],
  ['power',[0xf0]],
  ['logbase',[0xef,0x34]],
  ['integral',[0x24]],
  ['nderiv',[0x25]],
  ['summation',[0xef,0x33]],
];

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(2);
}

function argumentsByName(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key || !key.startsWith('--') || value === undefined)
      fail('arguments must be --name value pairs');
    result[key.slice(2)] = value;
  }
  return result;
}

function digest(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function main() {
  const args = argumentsByName(process.argv.slice(2));
  for (const name of ['prefix','macro','trace','output'])
    if (!args[name]) fail(`missing --${name}`);
  const traceSha256 = digest(args.trace);
  const transitions = CASES.map(([name,sourceToken]) => {
    const statePath = side => `${args.prefix}-${name}-${side}`;
    const pre = capture.captureStatePaths(
      `${statePath('pre')}.ram`,`${statePath('pre')}.png`,`${name} pre`);
    const post = capture.captureStatePaths(
      `${statePath('post')}.ram`,`${statePath('post')}.png`,`${name} post`);
    const before = capture.decodeSparse(pre);
    const after = capture.decodeSparse(post);
    const inserted = rom.editorInsertStructuralTemplate(
      before,sourceToken,font);
    if (!capture.sameState(inserted.state,after))
      throw new Error(`${name}: translated insertion does not match post-state`);
    return {
      name:`${name}_before_fraction`,
      trace_sha256:traceSha256,
      final_lcd_sha256:post.lcd_bitmap_sha256,
      source_token:sourceToken,
      mutation:inserted.mutation,
      pre,
      post,
    };
  });
  const payload = `${JSON.stringify({
    schema:1,
    capture:{
      macro:args.macro,
      macro_sha256:digest(args.macro),
      trace_sha256:traceSha256,
    },
    transitions,
  },null,2)}\n`;
  fs.writeFileSync(args.output,payload);
  process.stdout.write(`wrote ${args.output}: ${transitions.length} transitions\n`);
}

if (require.main === module) main();
